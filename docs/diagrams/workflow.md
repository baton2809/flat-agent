# Workflow Diagram — Request Execution Flow

Пошаговое выполнение запроса, включая ветки ошибок.

```mermaid
flowchart TD
    START([Пользователь отправляет сообщение]) --> ENTRY

    ENTRY{Telegram или\nREST API?}
    ENTRY -->|Telegram| TG_RECV[bot.py: handle_message\nили handle_document]
    ENTRY -->|POST /chat| API_RECV[routes.py: chat_endpoint\nrun_in_executor]

    TG_RECV --> BUILD_STATE
    API_RECV --> BUILD_STATE

    BUILD_STATE[Собрать AgentState:\nmessages + user_id + route=None] --> GRAPH_INVOKE

    GRAPH_INVOKE[langgraph.invoke с\nthread_id=user_id] --> ROUTER

    subgraph ROUTER_NODE["[router_node]"]
        ROUTER{Fast-path\nmatches?}
        ROUTER -->|"Привет / что умеешь\nключевая ставка / курс"| FP_CHAT[route = 'chat']
        ROUTER -->|"найди / новостройки в..."| FP_SEARCH[route = 'search']
        ROUTER -->|"mortgage follow-up\n(prev AI msg = расчёт)"| FP_MORT[route = 'mortgage']
        ROUTER -->|Нет совпадений| LLM_CLASSIFY

        LLM_CLASSIFY[GigaChat function calling\nRouteDecision temp=0.0]
        LLM_CLASSIFY -->|Успех| ROUTE_VALID{route valid?}
        LLM_CLASSIFY -->|Ошибка / timeout| FALLBACK_CHAT_R[route = 'chat'\nfallback]
        ROUTE_VALID -->|Да| ROUTE_SET[route = mortgage/compare/search/chat]
        ROUTE_VALID -->|Нет| FALLBACK_CHAT_R
    end

    FP_CHAT --> MEM_NODE
    FP_SEARCH --> MEM_NODE
    FP_MORT --> MEM_NODE
    ROUTE_SET --> MEM_NODE
    FALLBACK_CHAT_R --> MEM_NODE

    subgraph MEM_EXTRACT["[memory_extraction_node] — все маршруты"]
        MEM_NODE[extract_and_store_facts\nuser_id + last_message]
        MEM_NODE --> LLM_MEM{LLM извлечение\nфакта}
        LLM_MEM -->|Есть факт| STORE_FACT[INSERT OR IGNORE\nuser_memory]
        LLM_MEM -->|Нет факта| MEM_SKIP[Пропустить]
        LLM_MEM -->|LLM ошибка| REGEX_MEM[Regex fallback:\nимя / бюджет / семья]
        REGEX_MEM -->|Найден| STORE_FACT
        REGEX_MEM -->|Не найден| MEM_SKIP
    end

    STORE_FACT --> DISPATCH
    MEM_SKIP --> DISPATCH

    DISPATCH{Dispatch\nпо route}

    DISPATCH -->|mortgage| MORT_NODE
    DISPATCH -->|compare| COMP_NODE
    DISPATCH -->|search| SRCH_NODE
    DISPATCH -->|chat| CHAT_NODE

    subgraph MORTGAGE["[mortgage_node]"]
        MORT_NODE[Regex parse:\nsumma / rate / term]
        MORT_NODE --> MORT_PARAMS{Все параметры\nизвестны?}
        MORT_PARAMS -->|Нет rate| CBR_RATE[get_current_rate\n+2% spread]
        CBR_RATE -->|Успех| MORT_CALC
        CBR_RATE -->|ExternalAPIError| MORT_ASK_RATE[Попросить ставку\nу пользователя]
        MORT_PARAMS -->|Нет sum/term| MORT_SCAN[Сканировать\nисторию сообщений]
        MORT_SCAN --> MORT_PARAMS2{Заполнено?}
        MORT_PARAMS2 -->|Нет| MORT_ASK[Попросить\nпропущенные параметры]
        MORT_PARAMS2 -->|Да| MORT_CALC
        MORT_PARAMS -->|Все есть| MORT_CALC
        MORT_CALC[calculate_mortgage\nаннуитетная формула]
        MORT_CALC -->|ValidationError| MORT_VAL_ERR[node_error_response\nValidationError]
        MORT_CALC -->|Успех| MORT_FMT[Форматировать\nрезультат]
    end

    subgraph COMPARE["[compare_node]"]
        COMP_NODE[LLM comparison\nllm_call_direct temp=0.3]
        COMP_NODE -->|Успех len>100| COMP_OK[Ответ пользователю]
        COMP_NODE -->|LLMError / len<100| COMP_FB{Keyword\nmatch?}
        COMP_FB -->|первичка/вторичка| COMP_TMPL1[Шаблон: первичка vs вторичка]
        COMP_FB -->|центр/спальный| COMP_TMPL2[Шаблон: центр vs спальный]
        COMP_FB -->|Нет| COMP_TMPL3[Generic: укажите критерии]
    end

    subgraph SEARCH["[search_node]"]
        SRCH_NODE[enhance_real_estate_query]
        SRCH_NODE --> DDG[DuckDuckGo DDGS.text\nmax_results=12 ru-ru]
        DDG -->|0 результатов| DDG_RETRY[Retry с timelimit=y]
        DDG -->|Результаты| FILTER[filter_relevant_results\nwhitelist + term score]
        DDG_RETRY -->|Пусто| SRCH_EMPTY[Fallback: уточните запрос\n+ ссылки на ЦИАН/Авито]
        DDG_RETRY -->|Результаты| FILTER
        FILTER -->|Прошли| LLM_FMT[LLM format temp=0.3\nSystem prompt constraints]
        FILTER -->|Всё отфильтровано| RELAX[top-3 raw results]
        RELAX --> LLM_FMT
        LLM_FMT -->|len>50| SRCH_OK[Ответ + ссылки]
        LLM_FMT -->|LLMError / len<50| SRCH_TMPL[Шаблонный список\n+ ссылки]
        DDG -->|ExternalAPIError| SRCH_ERR[node_error_response\nExternalAPIError]
    end

    subgraph CHAT["[chat_node]"]
        CHAT_NODE{CBR request?}
        CHAT_NODE -->|Да: ставка/курс| CBR_HANDLER[get_current_rate\nили get_cbr_data]
        CBR_HANDLER -->|Успех| CBR_RESP[Форматировать CBR ответ]
        CBR_HANDLER -->|ExternalAPIError| CHAT_ERR_CBR[user_message_for_error]
        CHAT_NODE -->|Нет| MEM_CTX[Получить memory_context\nget_user_name]
        MEM_CTX --> CHAT_LLM[LLM: system prompt domain restriction\nmessages-10 sliding window\ntemp=0.3]
        CHAT_LLM -->|Успех| CHAT_OK[Ответ пользователю]
        CHAT_LLM -->|LLMError| CHAT_ERR[user_message_for_error]
    end

    MORT_FMT --> END_NODE
    MORT_ASK --> END_NODE
    MORT_ASK_RATE --> END_NODE
    MORT_VAL_ERR --> END_NODE
    COMP_OK --> END_NODE
    COMP_TMPL1 --> END_NODE
    COMP_TMPL2 --> END_NODE
    COMP_TMPL3 --> END_NODE
    SRCH_OK --> END_NODE
    SRCH_TMPL --> END_NODE
    SRCH_EMPTY --> END_NODE
    SRCH_ERR --> END_NODE
    CBR_RESP --> END_NODE
    CBR_HANDLER --> END_NODE
    CHAT_OK --> END_NODE
    CHAT_ERR --> END_NODE
    CHAT_ERR_CBR --> END_NODE

    END_NODE[AIMessage в state.messages] --> DELIVER

    DELIVER{Канал доставки}
    DELIVER -->|Telegram| TG_REPLY[reply_text Markdown\nСплит >4096\nFallback plain text]
    DELIVER -->|REST API| JSON_RESP[ChatResponse JSON]

    TG_REPLY --> DONE([Пользователь получил ответ])
    JSON_RESP --> DONE
```

## Легенда ветвей ошибок

| Ветка ошибки | Триггер | Поведение |
|---|---|---|
| LLM недоступен (router) | GigaChat timeout/exception | `route = "chat"`, продолжение |
| LLM недоступен (compare) | `LLMError` или `len < 100` | Keyword-based fallback шаблон |
| LLM недоступен (search format) | `LLMError` или `len < 50` | Шаблонный список + ссылки |
| LLM недоступен (chat) | `LLMError` | "Сервис временно недоступен" |
| CBR API недоступен | `ExternalAPIError` | Кэш (1ч) или просим ввести вручную |
| DDG недоступен | `ExternalAPIError` | "Не удалось получить данные" |
| ValidationError (ипотека) | Негативные/нулевые параметры | "Некорректные параметры" |
| Пустой DDG результат | `results == []` | Текстовый совет + ссылки |
| Telegram Markdown fail | Исключение при `reply_text` | Retry без `parse_mode='Markdown'` |
