#!/bin/bash

# FlatAgent Management Script
# Usage: ./manage.sh [start|stop|restart|status|logs]

VENV_PYTHON="/Users/a.butomau/Development/master/sberuniversity/.venv/bin/python"
MAIN_SCRIPT="$VENV_PYTHON main.py"
BOT_SCRIPT="$VENV_PYTHON telegram_bot/bot.py"
MAIN_LOG="logs/main.log"
BOT_LOG="logs/bot.log"
PORT=8000

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_status() {
    echo -e "${GREEN}[ok]${NC} $1"
}

print_error() {
    echo -e "${RED}[error]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[warn]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[info]${NC} $1"
}

kill_by_name() {
    local process_name=$1
    local pids=$(pgrep -f "$process_name")

    if [ ! -z "$pids" ]; then
        pkill -f "$process_name" 2>/dev/null
        sleep 2
        pkill -9 -f "$process_name" 2>/dev/null
        print_status "killed: $process_name"
    fi
}

kill_port() {
    local port=$1
    local pid=$(lsof -ti:$port 2>/dev/null)

    if [ ! -z "$pid" ]; then
        kill -9 $pid 2>/dev/null
        sleep 1
        print_status "freed port $port"
    fi
}

is_running() {
    pgrep -f "$1" > /dev/null
}

start_services() {
    echo "starting FlatAgent services..."
    mkdir -p logs

    if [ ! -f "main.py" ]; then
        print_error "main.py not found. make sure you are in the flat_agent directory."
        exit 1
    fi

    if is_running "$MAIN_SCRIPT"; then
        print_warning "FastAPI server already running"
    else
        print_info "starting FastAPI server..."
        nohup $MAIN_SCRIPT > $MAIN_LOG 2>&1 &
        MAIN_PID=$!
        sleep 3

        if kill -0 $MAIN_PID 2>/dev/null; then
            print_status "FastAPI server started (PID: $MAIN_PID)"
        else
            print_error "failed to start FastAPI server. check $MAIN_LOG"
            return 1
        fi
    fi

    if is_running "$BOT_SCRIPT"; then
        print_warning "Telegram bot already running"
    else
        print_info "starting Telegram bot..."
        nohup env PYTHONPATH="$(pwd)" $BOT_SCRIPT > $BOT_LOG 2>&1 &
        BOT_PID=$!
        sleep 3

        if kill -0 $BOT_PID 2>/dev/null; then
            print_status "Telegram bot started (PID: $BOT_PID)"
        else
            print_error "failed to start Telegram bot. check $BOT_LOG"
            return 1
        fi
    fi

    echo ""
    print_status "all services started"
    echo "  FastAPI: http://localhost:$PORT"
    echo "  Telegram bot polling for messages"
    echo "  log files: $MAIN_LOG, $BOT_LOG"
}

stop_services() {
    echo "stopping FlatAgent services..."

    kill_by_name "$MAIN_SCRIPT"
    kill_by_name "$BOT_SCRIPT"
    kill_port $PORT

    sleep 2

    if is_running "$MAIN_SCRIPT" || is_running "$BOT_SCRIPT"; then
        print_warning "force killing remaining processes..."
        pkill -9 -f "$MAIN_SCRIPT" 2>/dev/null
        pkill -9 -f "$BOT_SCRIPT" 2>/dev/null
    fi

    print_status "all services stopped"
}

show_status() {
    echo "FlatAgent services status"
    echo "--------------------------"

    if is_running "$MAIN_SCRIPT"; then
        MAIN_PID=$(pgrep -f "$MAIN_SCRIPT")
        print_status "FastAPI server running (PID: $MAIN_PID)"
    else
        print_error "FastAPI server not running"
    fi

    if is_running "$BOT_SCRIPT"; then
        BOT_PID=$(pgrep -f "$BOT_SCRIPT")
        print_status "Telegram bot running (PID: $BOT_PID)"
    else
        print_error "Telegram bot not running"
    fi

    echo ""
    echo "port status:"
    if lsof -ti:$PORT > /dev/null 2>&1; then
        PORT_PID=$(lsof -ti:$PORT)
        print_status "port $PORT in use (PID: $PORT_PID)"
    else
        print_error "port $PORT is free"
    fi

    echo ""
    echo "log files:"
    for log in $MAIN_LOG $BOT_LOG; do
        if [ -f "$log" ]; then
            LOG_SIZE=$(ls -lh "$log" | awk '{print $5}')
            LOG_LINES=$(wc -l < "$log")
            echo "  $log: $LOG_SIZE ($LOG_LINES lines)"
        else
            echo "  $log not found"
        fi
    done
}

show_logs() {
    local service=$2

    case $service in
        "main"|"api"|"fastapi")
            if [ -f "$MAIN_LOG" ]; then
                echo "last 50 lines of FastAPI logs:"
                tail -50 "$MAIN_LOG"
            else
                print_error "$MAIN_LOG not found"
            fi
            ;;
        "bot"|"telegram")
            if [ -f "$BOT_LOG" ]; then
                echo "last 50 lines of Telegram bot logs:"
                tail -50 "$BOT_LOG"
            else
                print_error "$BOT_LOG not found"
            fi
            ;;
        ""|"all")
            if [ -f "$MAIN_LOG" ] && [ -f "$BOT_LOG" ]; then
                echo "FastAPI logs (last 50 lines):"
                tail -50 "$MAIN_LOG"
                echo ""
                echo "Telegram bot logs (last 50 lines):"
                tail -50 "$BOT_LOG"
            else
                print_error "some log files not found"
            fi
            ;;
        *)
            print_error "unknown service: $service. use: main, bot, or all"
            ;;
    esac
}

run_tests() {
    local category=${2:-"all"}

    if [ ! -f "tests/run_tests.py" ]; then
        print_error "test runner not found. make sure tests/run_tests.py exists."
        exit 1
    fi

    echo "running tests: $category"
    echo ""

    python tests/run_tests.py "$category"
}

show_usage() {
    echo "FlatAgent Management Script"
    echo ""
    echo "Usage: ./manage.sh [COMMAND] [OPTIONS]"
    echo ""
    echo "Commands:"
    echo "  start     - start all services"
    echo "  stop      - stop all services"
    echo "  restart   - restart all services"
    echo "  status    - show service status"
    echo "  logs      - show logs [main|bot|all]"
    echo "  test      - run tests [unit|integration|system|all]"
    echo ""
    echo "Examples:"
    echo "  ./manage.sh start"
    echo "  ./manage.sh restart"
    echo "  ./manage.sh logs bot"
    echo "  ./manage.sh test unit"
    echo "  ./manage.sh status"
}

case "$1" in
    "start")
        start_services
        ;;
    "stop")
        stop_services
        ;;
    "restart")
        stop_services
        sleep 2
        start_services
        ;;
    "status")
        show_status
        ;;
    "logs")
        show_logs "$@"
        ;;
    "test")
        run_tests "$@"
        ;;
    "")
        show_usage
        ;;
    *)
        print_error "unknown command: $1"
        echo ""
        show_usage
        exit 1
        ;;
esac
