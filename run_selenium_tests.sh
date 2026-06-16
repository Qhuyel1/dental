#!/bin/bash
# run_selenium_tests.sh
# Script chạy toàn bộ Selenium E2E tests cho dự án Dental Management
#
# Cách dùng:
#   chmod +x run_selenium_tests.sh
#   ./run_selenium_tests.sh             # Chạy tất cả
#   ./run_selenium_tests.sh auth        # Chỉ chạy module auth
#   ./run_selenium_tests.sh patients    # Chỉ chạy module patients
#   ./run_selenium_tests.sh invoices    # Chỉ chạy module invoices


set -e

# Màu sắc cho output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       🦷 Dental Management - Selenium E2E Tests              ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Kiểm tra Python venv
if [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif [ -f "venv/bin/python" ]; then
    PYTHON="venv/bin/python"
else
    PYTHON="python3"
fi

echo -e "${YELLOW}▶ Dùng Python: $PYTHON${NC}"
echo -e "${YELLOW}▶ Thư mục làm việc: $(pwd)${NC}"
echo ""

# Xác định module cần chạy
MODULE=${1:-""}

if [ -z "$MODULE" ]; then
    # Chạy tất cả
    echo -e "${GREEN}▶ Chạy TẤT CẢ Selenium E2E tests...${NC}"
    echo ""
    $PYTHON manage.py test selenium_tests --verbosity=2 2>&1
else
    # Chạy module cụ thể
    echo -e "${GREEN}▶ Chạy module: selenium_tests.test_${MODULE}${NC}"
    echo ""
    $PYTHON manage.py test selenium_tests.test_${MODULE} --verbosity=2 2>&1
fi

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                  ✅ TẤT CẢ TESTS ĐÃ PASS!                  ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
else
    echo -e "${RED}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║              ❌ CÓ TESTS THẤT BẠI!                          ║${NC}"
    echo -e "${RED}║  📸 Xem screenshots tại: selenium_tests/screenshots/         ║${NC}"
    echo -e "${RED}╚══════════════════════════════════════════════════════════════╝${NC}"
fi

exit $EXIT_CODE
