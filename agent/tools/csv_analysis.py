"""CSV analysis tool: OLS regression and Plotly charts for apartment data."""

import logging
import tempfile
from typing import Any

import pandas as pd
import numpy as np
import statsmodels.api as sm
import plotly.graph_objects as go
from plotly.subplots import make_subplots

logger = logging.getLogger(__name__)

# Column name patterns for auto-detection (lowercased substrings)
_PRICE_PATTERNS = ['цена', 'price', 'стоимость', 'cost', 'value', 'руб']
_AREA_PATTERNS = ['площадь', 'area', 'sqm', 'метр', 'кв.м', 'квм', 'м²', 'кв.м']
_ROOMS_PATTERNS = ['комнат', 'room', 'rooms', 'кол-во', 'количество комн', 'студ']
_FLOOR_PATTERNS = ['этаж', 'floor', 'этажность']
_TOTAL_FLOOR_PATTERNS = ['всего этаж', 'total_floor', 'этажей', 'floors']
_ID_PATTERNS = ['id', 'номер', 'number', '№', 'кв.', ' кв ', 'квартира']
_DISTRICT_PATTERNS = ['район', 'district', 'area_name', 'location', 'округ', 'город', 'корпус', 'секция', 'жк', 'адрес']
_BUILD_YEAR_PATTERNS = ['год', 'year', 'build', 'построен', 'постройки', 'сдача']
_PRICE_PER_SQM_PATTERNS = ['цена/м', 'price/m', 'руб/м', 'за м²', 'за кв', 'per_sqm', 'price_sqm']


def _find_column(df: pd.DataFrame, patterns: list[str], exclude_patterns: list[str] | None = None) -> str | None:
    """Return the first DataFrame column whose lowercased name contains any pattern.

    Skips columns matching exclude_patterns (used to avoid e.g. цена/м² when looking for цена).
    """
    for col in df.columns:
        col_lower = col.lower()
        if exclude_patterns and any(ep in col_lower for ep in exclude_patterns):
            continue
        if any(p in col_lower for p in patterns):
            return col
    return None


def _numeric_stats(df: pd.DataFrame, col: str) -> tuple[float, float] | None:
    """Return (median, max) for a column coerced to numeric. None if not numeric."""
    s = pd.to_numeric(
        df[col].astype(str).str.replace(r'[\s ]', '', regex=True).str.replace(',', '.'),
        errors='coerce'
    ).dropna()
    if len(s) < 3:
        return None
    return float(s.median()), float(s.max())


def _detect_columns_by_content(df: pd.DataFrame) -> dict[str, str | None]:
    """Guess column roles from value ranges when column names are not descriptive.

    Heuristics for apartment data:
      price       - numeric, median >= 500_000  (рублей)
      area        - numeric, median in [15, 500] (кв.м)
      rooms       - numeric, median in [1, 10], max <= 20
      floor       - numeric, median in [1, 40], max <= 100
      total_floors- numeric, median in [2, 60], max <= 120
      build_year  - numeric, median in [1900, 2100]
    """
    result: dict[str, str | None] = {
        'price': None, 'area': None, 'rooms': None, 'floor': None,
        'total_floors': None, 'id': None, 'district': None, 'build_year': None,
    }
    assigned: set[str] = set()

    stats: dict[str, tuple[float, float]] = {}
    for col in df.columns:
        s = _numeric_stats(df, col)
        if s is not None:
            stats[col] = s

    def pick(role: str, candidates: list[str]) -> None:
        for c in candidates:
            if c not in assigned:
                result[role] = c
                assigned.add(c)
                return

    # Price: largest median values
    price_candidates = sorted(
        [c for c, (med, _) in stats.items() if med >= 100_000],
        key=lambda c: stats[c][0], reverse=True
    )
    pick('price', price_candidates)

    # Build year: median between 1900 and 2100
    year_candidates = [c for c, (med, mx) in stats.items()
                       if 1900 <= med <= 2100 and mx <= 2100 and c not in assigned]
    pick('build_year', year_candidates)

    # Area: median 15..500
    area_candidates = sorted(
        [c for c, (med, _) in stats.items() if 15 <= med <= 500 and c not in assigned],
        key=lambda c: stats[c][0], reverse=True
    )
    pick('area', area_candidates)

    # Total floors: median 2..60, max <= 120
    tf_candidates = sorted(
        [c for c, (med, mx) in stats.items() if 2 <= med <= 60 and mx <= 120 and c not in assigned],
        key=lambda c: stats[c][0], reverse=True
    )
    pick('total_floors', tf_candidates)

    # Floor: median 1..40, max <= 100
    fl_candidates = [c for c, (med, mx) in stats.items()
                     if 1 <= med <= 40 and mx <= 100 and c not in assigned]
    pick('floor', fl_candidates)

    # Rooms: median 1..10, max <= 20
    room_candidates = [c for c, (med, mx) in stats.items()
                       if 1 <= med <= 10 and mx <= 20 and c not in assigned]
    pick('rooms', room_candidates)

    # ID: integer-looking column, likely sequential
    id_candidates = [c for c, (med, mx) in stats.items()
                     if c not in assigned and mx < 100_000]
    pick('id', id_candidates)

    logger.info("content-based column detection: %s", {k: v for k, v in result.items() if v})
    return result


_CATEGORY_PATTERNS = ['отделк', 'finish', 'тип', 'type', 'класс', 'class', 'вид', 'статус']


def _find_category_column(df: pd.DataFrame, skip_cols: set | None = None) -> str | None:
    """Find a column suitable for coloring: 2–10 unique string values, not all numeric.

    Checks named patterns first, then falls back to any low-cardinality text column.
    """
    skip = skip_cols or set()

    col = _find_column(df, _CATEGORY_PATTERNS)
    if col is not None and col not in skip:
        return col

    for c in df.columns:
        if c in skip:
            continue
        series = df[c].dropna().astype(str)
        n_unique = series.nunique()
        if 2 <= n_unique <= 10:
            numeric_ratio = pd.to_numeric(series, errors='coerce').notna().mean()
            if numeric_ratio < 0.8:
                return c
    return None


def _find_binary_split_column(df: pd.DataFrame, skip_cols: set) -> tuple[str, list] | None:
    """Find a column with exactly 2 unique values in 30–70% balance.

    Suitable for splitting the dataset into two groups for separate OLS models.
    Considers both string and numeric columns with exactly 2 distinct values.

    Returns (col_name, [val1, val2]) sorted by frequency desc, or None.
    """
    for col in df.columns:
        if col in skip_cols:
            continue
        series = df[col].dropna()
        if series.nunique() != 2:
            continue
        counts = series.value_counts(normalize=True)
        minority_ratio = float(counts.iloc[-1])
        if minority_ratio >= 0.30:
            logger.info(
                "binary split column: %r (minority=%.0f%%)", col, minority_ratio * 100
            )
            return col, list(counts.index)
    return None


def _detect_columns(df: pd.DataFrame) -> dict[str, str | None]:
    """Auto-detect meaningful column roles by name, then fall back to content heuristics."""
    by_name = {
        'price': _find_column(df, _PRICE_PATTERNS, exclude_patterns=_PRICE_PER_SQM_PATTERNS),
        'area': _find_column(df, _AREA_PATTERNS),
        'rooms': _find_column(df, _ROOMS_PATTERNS),
        'floor': _find_column(df, _FLOOR_PATTERNS, exclude_patterns=['этажей', 'total']),
        'total_floors': _find_column(df, _TOTAL_FLOOR_PATTERNS),
        'id': _find_column(df, _ID_PATTERNS),
        'district': _find_column(df, _DISTRICT_PATTERNS),
        'build_year': _find_column(df, _BUILD_YEAR_PATTERNS),
        'category': _find_category_column(df),
    }

    if by_name['price'] or by_name['area']:
        return by_name

    logger.info("name-based detection found nothing, trying content-based heuristics")
    result = _detect_columns_by_content(df)
    result['category'] = _find_category_column(df)
    return result


def _to_numeric(df: pd.DataFrame, col: str) -> pd.Series:
    """Coerce a column to float.

    Handles Russian number format:
      - decimal comma: '38,5' -> 38.5
      - space as thousand separator: '1 500 000' -> 1500000
    """
    s = df[col].astype(str).str.strip()
    s = s.str.replace(r'(\d),(\d{1,2})$', r'\1.\2', regex=True)
    s = s.str.replace(r'(\d),(\d{1,2})\b', r'\1.\2', regex=True)
    s = s.str.replace(r'[\s\u00a0,]', '', regex=True)
    return pd.to_numeric(s, errors='coerce')


def _build_ols_model(df: pd.DataFrame, cols: dict[str, str | None]) -> dict[str, Any] | None:
    """Build OLS regression predicting price from available features.

    Returns dict with model, feature_names, X, y, fitted_values, residuals.
    Returns None if insufficient data.
    """
    if cols['price'] is None:
        logger.warning("no price column detected, skipping OLS")
        return None

    price = _to_numeric(df, cols['price'])

    features = {}
    feature_labels = {}

    for role, label in [
        ('area', 'Площадь (кв.м)'),
        ('rooms', 'Комнаты'),
        ('floor', 'Этаж'),
        ('total_floors', 'Этажей в доме'),
        ('build_year', 'Год постройки'),
    ]:
        if cols.get(role):
            s = _to_numeric(df, cols[role])
            valid_ratio = s.notna().mean()
            if valid_ratio >= 0.7:
                features[cols[role]] = s
                feature_labels[cols[role]] = label
            else:
                logger.info(
                    "skipping feature %r: only %.0f%% numeric values", cols[role], valid_ratio * 100
                )

    if not features:
        logger.warning("no numeric feature columns detected")
        return None

    feat_df = pd.DataFrame(features)
    combined = pd.concat([price.rename('price'), feat_df], axis=1).dropna()

    if len(combined) < 5:
        logger.warning("too few rows after dropna: %d", len(combined))
        return None

    y = combined['price']
    X_raw = combined[list(features.keys())]
    X = sm.add_constant(X_raw)

    model = sm.OLS(y, X).fit()

    return {
        'model': model,
        'X': X_raw,
        'y': y,
        'fitted': model.fittedvalues,
        'residuals': model.resid,
        'feature_labels': feature_labels,
        'price_col': cols['price'],
    }


def _build_ols_split(
    df: pd.DataFrame,
    cols: dict[str, str | None],
    split_col: str,
    split_vals: list,
) -> list[tuple[str, dict]]:
    """Build OLS models for each value of a binary split column.

    Requires at least 10 rows per group.
    Returns list of (label, ols_result) for groups with successful models.
    """
    results = []
    for val in split_vals:
        mask = df[split_col].astype(str) == str(val)
        sub = df[mask].reset_index(drop=True)
        if len(sub) < 10:
            logger.warning("group %r too small (%d rows), skipping", val, len(sub))
            continue
        ols = _build_ols_model(sub, cols)
        if ols is not None:
            results.append((str(val), ols))
    return results


def _format_price(val: float) -> str:
    """Format price value to human-readable string (млн/тыс)."""
    if val >= 1_000_000:
        return f"{val / 1_000_000:.2f} млн"
    if val >= 1_000:
        return f"{val / 1_000:.0f} тыс"
    return f"{val:.0f}"


_CATEGORY_COLORS = [
    '#e05c5c', '#4a90d9', '#27ae60', '#f39c12', '#8e44ad',
    '#16a085', '#d35400', '#2c3e50',
]


def _build_charts(
    df: pd.DataFrame,
    cols: dict[str, str | None],
    ols_models: list[tuple[str, dict]],
) -> str | None:
    """Generate 4-panel Plotly chart and export as PNG.

    Layout:
      Row 1: [Price histogram] | [Price vs Area scatter, colored by category, trend lines]
      Row 2: [OLS Actual vs Predicted (all models)]  | [OLS Residuals (all models)]

    ols_models: list of (label, ols_result). Label is "" for single-model case.
    """
    if cols['price'] is None:
        return None

    has_area = cols['area'] is not None
    price_series = _to_numeric(df, cols['price'])
    area_series = _to_numeric(df, cols['area']) if has_area else None
    cat_col = cols.get('category')

    # Subplot titles depend on whether we have split models
    if len(ols_models) == 2:
        ols_title = f'OLS: факт vs прогноз ({ols_models[0][0]} / {ols_models[1][0]})'
        resid_title = f'Остатки ({ols_models[0][0]} / {ols_models[1][0]})'
    elif len(ols_models) == 1 and ols_models[0][0]:
        ols_title = f'OLS: факт vs прогноз ({ols_models[0][0]})'
        resid_title = f'Остатки регрессии ({ols_models[0][0]})'
    else:
        ols_title = 'OLS: факт vs прогноз'
        resid_title = 'Остатки регрессии'

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=[
            'Распределение цен',
            f'Цена vs Площадь{(" (по " + cat_col + ")") if cat_col else ""}',
            ols_title,
            resid_title,
        ],
        vertical_spacing=0.14,
        horizontal_spacing=0.10,
    )

    fig.add_trace(
        go.Histogram(x=price_series.dropna(), nbinsx=25,
                     marker_color='steelblue', name='Цены'),
        row=1, col=1
    )

    if has_area and area_series is not None:
        mask = price_series.notna() & area_series.notna()
        x_all = area_series[mask].values
        y_all = price_series[mask].values

        if cat_col is not None:
            categories = df[cat_col].astype(str).fillna('?')
            unique_cats = sorted(categories[mask].unique())
        else:
            categories = pd.Series(['Все'] * len(df))
            unique_cats = ['Все']

        for i, cat in enumerate(unique_cats):
            color = _CATEGORY_COLORS[i % len(_CATEGORY_COLORS)]
            cat_mask = (categories[mask] == cat).values
            x_cat = x_all[cat_mask]
            y_cat = y_all[cat_mask]

            fig.add_trace(
                go.Scatter(
                    x=x_cat, y=y_cat, mode='markers', name=cat,
                    marker=dict(color=color, size=6, opacity=0.7),
                    legendgroup=cat,
                ),
                row=1, col=2
            )

            if len(x_cat) >= 3:
                try:
                    coef = np.polyfit(x_cat, y_cat, 1)
                    x_line = np.linspace(x_cat.min(), x_cat.max(), 100)
                    y_line = np.polyval(coef, x_line)
                    fig.add_trace(
                        go.Scatter(
                            x=x_line, y=y_line, mode='lines', name=f'{cat} (тренд)',
                            line=dict(color=color, width=2),
                            legendgroup=cat, showlegend=False,
                        ),
                        row=1, col=2
                    )
                except Exception:
                    pass

        fig.update_xaxes(title_text='Площадь, кв.м', row=1, col=2)
        fig.update_yaxes(title_text='Цена, руб.', row=1, col=2)

    if ols_models:
        all_vals = []
        for i, (label, ols) in enumerate(ols_models):
            color = _CATEGORY_COLORS[i % len(_CATEGORY_COLORS)]
            y_actual = ols['y']
            y_fitted = ols['fitted']
            trace_name = f'{label} (OLS)' if label else 'OLS точки'
            fig.add_trace(
                go.Scatter(
                    x=y_actual, y=y_fitted, mode='markers',
                    marker=dict(color=color, size=6, opacity=0.7),
                    name=trace_name,
                    legendgroup=f'ols_{i}',
                ),
                row=2, col=1
            )
            all_vals += [float(y_actual.min()), float(y_actual.max()),
                         float(y_fitted.min()), float(y_fitted.max())]

        if all_vals:
            mn, mx = min(all_vals), max(all_vals)
            fig.add_trace(
                go.Scatter(
                    x=[mn, mx], y=[mn, mx], mode='lines',
                    line=dict(color='gray', dash='dash', width=1.5),
                    name='Идеал', showlegend=False,
                ),
                row=2, col=1
            )
        fig.update_xaxes(title_text='Факт, руб.', row=2, col=1)
        fig.update_yaxes(title_text='Прогноз, руб.', row=2, col=1)

    if ols_models:
        x_min_all, x_max_all = [], []
        for i, (label, ols) in enumerate(ols_models):
            color_base = _CATEGORY_COLORS[i % len(_CATEGORY_COLORS)]
            y_fitted = ols['fitted']
            residuals = ols['residuals']

            abs_resid = residuals.abs()
            threshold = abs_resid.quantile(0.85)
            colors_resid = [color_base if v >= threshold else '#aaaaaa' for v in abs_resid]

            trace_name = f'{label} (остатки)' if label else 'Остатки'
            fig.add_trace(
                go.Scatter(
                    x=y_fitted, y=residuals, mode='markers',
                    marker=dict(color=colors_resid, size=6, opacity=0.8),
                    name=trace_name,
                    legendgroup=f'ols_{i}',
                ),
                row=2, col=2
            )
            x_min_all.append(float(y_fitted.min()))
            x_max_all.append(float(y_fitted.max()))

        # Zero reference line as a trace (more compatible than add_hline across Plotly versions)
        if x_min_all:
            fig.add_trace(
                go.Scatter(
                    x=[min(x_min_all), max(x_max_all)], y=[0, 0], mode='lines',
                    line=dict(color='gray', dash='dash', width=1.5),
                    name='y=0', showlegend=False,
                ),
                row=2, col=2
            )
        fig.update_xaxes(title_text='Прогноз, руб.', row=2, col=2)
        fig.update_yaxes(title_text='Остаток, руб.', row=2, col=2)

    fig.update_layout(
        height=820,
        width=1100,
        title_text='Анализ данных квартир',
        template='plotly_white',
        legend=dict(
            orientation='h',
            yanchor='bottom', y=1.02,
            xanchor='right', x=1,
        ),
        margin=dict(t=80, b=40),
    )

    tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    tmp.close()
    fig.write_image(tmp.name, scale=1.5)
    return tmp.name


def _describe_object(
    df: pd.DataFrame,
    cols: dict[str, str | None],
    idx: int,
    rank: int,
    price: pd.Series,
    extra_lines: list[str],
) -> str:
    """Format one apartment entry for the recommendation list."""
    id_str = str(df[cols['id']].iloc[idx]) if cols['id'] is not None else f"#{idx}"
    header = f"{rank}. Объект {id_str}"
    lines = [header, f"   Цена: {_format_price(price[idx])} руб."]
    lines.extend(extra_lines)
    return "\n".join(lines)


def _find_best_deal(
    df: pd.DataFrame,
    cols: dict[str, str | None],
    ols: dict[str, Any] | None,
    top_n: int = 3,
) -> str:
    """Return recommendation text with top N underpriced apartments."""
    if cols['price'] is None:
        return "Нет данных о ценах для анализа."

    price = _to_numeric(df, cols['price'])

    if ols is None:
        if cols['area'] is not None:
            area = _to_numeric(df, cols['area'])
            price_per_sqm = price / area
            valid = price_per_sqm.dropna()
            if valid.empty:
                return "Нет достаточных данных."
            top_indices = list(valid.nsmallest(top_n).index)
            lines = [f"Топ-{top_n} по цене за кв.м:"]
            for rank, idx in enumerate(top_indices, 1):
                id_str = str(df[cols['id']].iloc[idx]) if cols['id'] is not None else f"#{idx}"
                lines.append(
                    f"{rank}. Объект {id_str} - "
                    f"{_format_price(price[idx])} руб., "
                    f"{area[idx]:.0f} кв.м, "
                    f"{_format_price(price_per_sqm[idx])} руб./кв.м"
                )
            return "\n".join(lines)

        top_indices = list(price.dropna().nsmallest(top_n).index)
        lines = [f"Топ-{top_n} по цене:"]
        for rank, idx in enumerate(top_indices, 1):
            id_str = str(df[cols['id']].iloc[idx]) if cols['id'] is not None else f"#{idx}"
            lines.append(f"{rank}. Объект {id_str} - {_format_price(price[idx])} руб.")
        return "\n".join(lines)

    diff = ols['y'] - ols['fitted']
    top_indices = list(diff.nsmallest(top_n).index)

    model = ols['model']
    result_lines = [
        f"Топ-{top_n} недооцененных объектов по OLS (R² = {model.rsquared:.3f}):",
        "(скидка = прогноз модели минус фактическая цена)",
    ]

    area_series = _to_numeric(df, cols['area']) if cols['area'] is not None else None
    rooms_series = _to_numeric(df, cols['rooms']) if cols['rooms'] is not None else None
    floor_series = _to_numeric(df, cols['floor']) if cols['floor'] is not None else None

    for rank, idx in enumerate(top_indices, 1):
        actual = float(ols['y'][idx])
        predicted = float(ols['fitted'][idx])
        discount = predicted - actual
        discount_pct = discount / predicted * 100 if predicted > 0 else 0.0

        id_str = str(df[cols['id']].iloc[idx]) if cols['id'] is not None else f"#{idx}"
        entry = [
            f"{rank}. Объект {id_str}",
            f"   Цена:    {_format_price(actual)} руб.",
            f"   Прогноз: {_format_price(predicted)} руб.",
            f"   Скидка:  {_format_price(discount)} руб. ({discount_pct:.1f}%)",
        ]

        if area_series is not None and idx in area_series.index and pd.notna(area_series[idx]):
            entry.append(f"   Площадь: {area_series[idx]:.0f} кв.м")
        if rooms_series is not None and idx in rooms_series.index and pd.notna(rooms_series[idx]):
            entry.append(f"   Комнат:  {int(rooms_series[idx])}")
        if floor_series is not None and idx in floor_series.index and pd.notna(floor_series[idx]):
            entry.append(f"   Этаж:    {int(floor_series[idx])}")
        if cols['district'] is not None:
            entry.append(f"   Район:   {df[cols['district']].iloc[idx]}")

        result_lines.append("\n".join(entry))

    return "\n\n".join(result_lines)


def _format_ols_text(ols_models: list[tuple[str, dict]]) -> str:
    """Format OLS summary text for one or two models."""
    if not ols_models:
        return "OLS не удалось построить (недостаточно числовых колонок или данных)."

    parts = []
    for label, ols in ols_models:
        model = ols['model']
        header = f"OLS регрессия{' - ' + label if label else ''}: R² = {model.rsquared:.3f}, N = {int(model.nobs)}"
        lines = [header]
        params = model.params
        pvalues = model.pvalues
        for feat, feat_label in ols['feature_labels'].items():
            if feat in params:
                coef = params[feat]
                pval = pvalues[feat]
                sign = "+" if coef >= 0 else ""
                sig = "***" if pval < 0.001 else "**" if pval < 0.01 else "*" if pval < 0.05 else ""
                lines.append(f"  {feat_label}: {sign}{coef:,.0f} руб. {sig}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts)


def _strip_col_names(df: pd.DataFrame) -> pd.DataFrame:
    """Strip leading/trailing whitespace from column names."""
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _is_valid_parse(df: pd.DataFrame) -> bool:
    """Return True if the DataFrame looks like it was parsed with the correct separator."""
    if len(df.columns) <= 1:
        return False
    if any(';' in str(c) for c in df.columns):
        return False
    if any('\t' in str(c) for c in df.columns):
        return False
    return True


def _read_csv_robust(file_path: str) -> pd.DataFrame | None:
    """Try to read CSV with auto-detected separator and encoding.

    Strategy:
    1. Try explicit common separators: ; , \\t | (Russian locale almost always uses ;)
    2. Fall back to pandas auto-detect via csv.Sniffer

    Tries encodings: utf-8-sig (BOM), utf-8, cp1251, latin-1.
    Returns DataFrame on success, None if completely unreadable.
    """
    encodings = ['utf-8-sig', 'utf-8', 'cp1251', 'latin-1']
    explicit_seps = [';', ',', '\t', '|']

    for enc in encodings:
        for sep in explicit_seps:
            try:
                df = pd.read_csv(file_path, encoding=enc, sep=sep)
                df = _strip_col_names(df)
                if _is_valid_parse(df):
                    logger.info(
                        "csv parsed: encoding=%s sep=%r cols=%d rows=%d",
                        enc, sep, len(df.columns), len(df)
                    )
                    return df
            except Exception:
                continue

        try:
            df = pd.read_csv(file_path, encoding=enc, sep=None, engine='python')
            df = _strip_col_names(df)
            if _is_valid_parse(df):
                logger.info(
                    "csv auto-detect ok: encoding=%s cols=%d rows=%d",
                    enc, len(df.columns), len(df)
                )
                return df
        except Exception:
            pass

    return None


def analyze_csv(file_path: str) -> dict[str, Any]:
    """Analyze a CSV file with apartment listings.

    Flow:
    1. Read CSV (auto-detects encoding and separator).
    2. Detect column roles by name, then by content heuristics.
    3. Build single OLS regression from all numeric features.
    4. Check for a balanced binary column (30-70% split) - if found,
       build two separate OLS models for each group.
    5. Generate 4-panel chart.

    Returns:
        dict with keys:
            'summary'        - short text overview
            'ols_text'       - OLS regression summary (one or two models)
            'recommendation' - best deal recommendation text
            'chart_path'     - path to PNG chart file (or None)
            'error'          - error message if analysis failed (or None)
    """
    df = _read_csv_robust(file_path)
    if df is None:
        return {
            'error': "Не удалось прочитать CSV. Проверьте формат файла.",
            'summary': '', 'ols_text': '', 'recommendation': '', 'chart_path': None,
        }

    logger.info("csv loaded: %d rows, %d cols: %s", len(df), len(df.columns), list(df.columns))

    cols = _detect_columns(df)
    logger.info("detected columns: %s", {k: v for k, v in cols.items() if v})

    detected = {k: v for k, v in cols.items() if v is not None}
    all_col_names = ', '.join(str(c) for c in df.columns)

    name_based = {
        'price': _find_column(df, _PRICE_PATTERNS),
        'area': _find_column(df, _AREA_PATTERNS),
    }
    used_content_detection = not (name_based['price'] or name_based['area'])

    summary_lines = [
        f"Файл загружен: {len(df)} объектов, {len(df.columns)} колонок.",
        f"Колонки в файле: {all_col_names}.",
    ]
    if detected:
        method = " (автодетект по значениям)" if used_content_detection else ""
        summary_lines.append(
            f"Распознаны{method}: {', '.join(f'{k}={v}' for k, v in detected.items())}."
        )
    else:
        sample = df.head(2).to_string(index=False)
        summary_lines.append(
            "Колонки не распознаны ни по именам, ни по значениям.\n"
            f"Пример данных:\n{sample}\n"
            "Переименуйте колонки: цена, площадь, комнаты, этаж, район."
        )

    if cols['price'] is not None:
        price = _to_numeric(df, cols['price']).dropna()
        summary_lines.append(
            f"Цены: мин {_format_price(price.min())} - макс {_format_price(price.max())} руб., "
            f"медиана {_format_price(price.median())} руб."
        )
    if cols['area'] is not None:
        area = _to_numeric(df, cols['area']).dropna()
        summary_lines.append(
            f"Площадь: {area.min():.0f} - {area.max():.0f} кв.м, медиана {area.median():.0f} кв.м."
        )

    summary = "\n".join(summary_lines)

    ols_single = _build_ols_model(df, cols)

    # Check for binary split column (skip already-assigned roles)
    assigned_cols = {v for v in cols.values() if v is not None}
    split_info = _find_binary_split_column(df, assigned_cols)

    ols_models: list[tuple[str, dict]] = []
    split_col_used: str | None = None

    if split_info is not None:
        split_col, split_vals = split_info
        split_models = _build_ols_split(df, cols, split_col, split_vals)

        if len(split_models) == 2:
            ols_models = split_models
            split_col_used = split_col
            logger.info("using split OLS models by column %r", split_col)
        else:
            logger.info("split produced %d models, falling back to single OLS", len(split_models))

    if not ols_models and ols_single is not None:
        ols_models = [("", ols_single)]

    if split_col_used:
        summary_lines_extra = f"Найдена колонка '{split_col_used}' с балансированным разделением - построены 2 регрессии."
        summary = summary + "\n" + summary_lines_extra

    ols_text = _format_ols_text(ols_models)

    primary_ols = ols_models[0][1] if ols_models else None
    recommendation = _find_best_deal(df, cols, primary_ols)
    if split_col_used and len(ols_models) == 2:
        second_rec = _find_best_deal(
            df[df[split_col_used].astype(str) == str(split_vals[1])].reset_index(drop=True),
            cols,
            ols_models[1][1],
        )
        recommendation = (
            f"[{ols_models[0][0]}]\n{recommendation}\n\n"
            f"[{ols_models[1][0]}]\n{second_rec}"
        )

    chart_path = None
    try:
        chart_path = _build_charts(df, cols, ols_models)
    except Exception as e:
        logger.warning("chart generation failed: %s", e)

    return {
        'summary': summary,
        'ols_text': ols_text,
        'recommendation': recommendation,
        'chart_path': chart_path,
        'error': None,
    }
