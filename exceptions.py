from enum import Enum
from typing import Dict, Optional

from fastapi import HTTPException, status


class ErrorCode(int, Enum):


    USER_NOT_FOUND = 10
    USER_NOT_IN_UNIT = 11
    USER_ALREADY_IN_UNIT = 12
    STUDENT_ID_ALREADY_EXISTS = 13
    UNIT_NOT_FOUND = 20
    UNIT_NOT_ALLOWED = 21
    INVALID_IMAGE_TYPE = 30

    INVALID_CREDENTIALS = 40
    INVALID_TOKEN = 41

    INSUFFICIENT_PERMISSION = 50
    HEADER_UNIT_REQUIRED = 60

    EVENT_NOT_FOUND = 70
    INVALID_REGISTRATION_TIME = 71
    INVALID_EVENT_TIME = 72
    EVENT_MUST_START_AFTER_REGISTRATION = 73
    INVALID_FORM_FIELD = 74
    MISSING_REQUIRED_FIELD = 75
    INVALID_OPTION = 76
    REGISTRATION_CLOSED = 77

    REPORT_NOT_FOUND = 80
    REPORT_ALREADY_EXISTS = 81

    REGISTRATION_NOT_FOUND = 90
    ALREADY_REGISTERED = 91
    EVENT_FULL = 92

    INVALID_POINT_VALUE = 100
    INVALID_UNIT_EVENT_TYPE_VALUE = 101

    SEMESTER_NOT_FOUND = 110
    ACTIVE_SEMESTER_NOT_FOUND = 111
    INVALID_SEMESTER_TIME = 112
    INVALID_ID_FORMAT = 113
    ACTIVE_SEMESTER_REQUIRED_FOR_EVENT = 114

    UNIT_EVENT_NOT_FOUND = 120
    INVALID_UNIT_EVENT_TYPE = 121
    UNIT_EVENT_SUBMISSION_ALREADY_EXISTS = 122
    UNIT_EVENT_SUBMISSION_NOT_FOUND = 123
    UNIT_EVENT_SUBMISSION_ALREADY_APPROVED = 124
    LIST_USER_ID_IS_REQUIRED = 125
    UNIT_NOT_ASSIGNED_TO_EVENT = 126
    UNIT_EVENT_SUBMISSION_CLOSED = 140
    REPORT_LOCKED = 127
    EVENT_LOCKED = 128
    QR_PAYLOAD_INVALID = 129
    QR_SESSION_NOT_FOUND = 130
    QR_SESSION_CLOSED = 131
    QR_PAYLOAD_EXPIRED = 132
    LOCATION_REQUIRED = 133
    LOCATION_OUT_OF_RANGE = 134
    DUPLICATE_CHECKIN = 135
    CHECKIN_QUEUE_UNAVAILABLE = 136
    QR_SESSION_TOO_LARGE = 137
    INVALID_QR_SESSION_TIME = 138
    USER_NOT_ALLOWED_FOR_EVENT = 139
    ATTENDANCE_CODE_INVALID = 141

ERROR_DEFINITIONS: Dict[ErrorCode, Dict[str, object]] = {
    ErrorCode.USER_NOT_FOUND: {
        "status": status.HTTP_404_NOT_FOUND,
        "message": "User khong ton tai",
    },
    ErrorCode.STUDENT_ID_ALREADY_EXISTS: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Mã sinh viên đã tồn tại",
    },
    ErrorCode.UNIT_NOT_FOUND: {
        "status": status.HTTP_404_NOT_FOUND,
        "message": "Unit khong ton tai",
    },
    ErrorCode.USER_ALREADY_IN_UNIT: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "User da la thanh vien cua unit trong semester nay",
    },
    ErrorCode.INVALID_IMAGE_TYPE: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Chi cho phep upload anh JPG/PNG",
    },
    ErrorCode.INVALID_CREDENTIALS: {
        "status": status.HTTP_401_UNAUTHORIZED,
        "message": "Thong tin dang nhap khong chinh xac",
    },
    ErrorCode.INVALID_TOKEN: {
        "status": status.HTTP_401_UNAUTHORIZED,
        "message": "Token khong hop le hoac da het han",
    },
    ErrorCode.INSUFFICIENT_PERMISSION: {
        "status": status.HTTP_403_FORBIDDEN,
        "message": "Ban khong co du quyen de thuc hien hanh dong nay",
    },
    ErrorCode.HEADER_UNIT_REQUIRED: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Thieu header X-Unit-Id",
    },
    ErrorCode.EVENT_NOT_FOUND: {
        "status": status.HTTP_404_NOT_FOUND,
        "message": "Su kien khong ton tai",
    },
    ErrorCode.REPORT_NOT_FOUND: {
        "status": status.HTTP_404_NOT_FOUND,
        "message": "Bao cao khong ton tai",
    },
    ErrorCode.REPORT_ALREADY_EXISTS: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Da co bao cao nhu vay roi",
    },
    ErrorCode.REGISTRATION_NOT_FOUND: {
        "status": status.HTTP_404_NOT_FOUND,
        "message": "Chua dang ky su tham gia su kien",
    },
    ErrorCode.ALREADY_REGISTERED: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Da dang ky su tham gia su kien roi",
    },
    ErrorCode.INVALID_REGISTRATION_TIME: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Thoi gian dang ky khong hop le",
    },
    ErrorCode.INVALID_EVENT_TIME: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Thoi gian su kien khong hop le",
    },
    ErrorCode.EVENT_MUST_START_AFTER_REGISTRATION: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Thoi gian su kien phai sau thoi gian dang ky",
    },
    ErrorCode.INVALID_POINT_VALUE: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Gia tri diem khong hop le",
    },
    ErrorCode.INVALID_UNIT_EVENT_TYPE_VALUE: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Loai su kien khong hop le",
    },
    ErrorCode.SEMESTER_NOT_FOUND: {
        "status": status.HTTP_404_NOT_FOUND,
        "message": "Semester khong ton tai",
    },
    ErrorCode.ACTIVE_SEMESTER_NOT_FOUND: {
        "status": status.HTTP_404_NOT_FOUND,
        "message": "Khong co semester dang hoat dong",
    },
    ErrorCode.INVALID_SEMESTER_TIME: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Thoi gian semester khong hop le",
    },
    ErrorCode.INVALID_ID_FORMAT: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "ID không đúng định dạng ObjectId",
    },
    ErrorCode.ACTIVE_SEMESTER_REQUIRED_FOR_EVENT: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Khong the tao su kien khi chua co semester dang hoat dong",
    },

    ErrorCode.UNIT_EVENT_NOT_FOUND: {
        "status": status.HTTP_404_NOT_FOUND,
        "message": "Sự kiện đẩy xuống đơn vị không tồn tại",
    },
    ErrorCode.UNIT_NOT_ALLOWED: {
        "status": status.HTTP_403_FORBIDDEN,
        "message": "Bạn kh thuộc đơn vị được giao",
    },
    ErrorCode.USER_NOT_IN_UNIT: {
        "status": status.HTTP_403_FORBIDDEN,
        "message": "Bạn phải thành viên của đơn vị được giao",
    },
    ErrorCode.UNIT_EVENT_SUBMISSION_ALREADY_EXISTS: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Đơn vị của bạn đã phản hồi sự kiện này rồi",
    },
    ErrorCode.UNIT_EVENT_SUBMISSION_NOT_FOUND: {
        "status": status.HTTP_404_NOT_FOUND,
        "message": "Đơn vị của bạn chưa phản hồi sự kiện này",
    },
    ErrorCode.UNIT_EVENT_SUBMISSION_ALREADY_APPROVED: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Phản hồi đã được duyệt, bạn chỉ có thể sửa khi ở trạng thái PENDING hoặc REJECTED",
    },
    ErrorCode.LIST_USER_ID_IS_REQUIRED: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Danh sách thành viên không được để trống",
    },
    ErrorCode.INVALID_FORM_FIELD: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Dữ liệu đăng ký kh hợp lệ",
    },
    ErrorCode.MISSING_REQUIRED_FIELD: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Dữ liệu bắt buộc",
    },
    ErrorCode.INVALID_OPTION: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Chưa chọn hoặc chọn không hợp lệ",
    },
    ErrorCode.REGISTRATION_CLOSED: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Sự kiện đã đóng",
    },
    ErrorCode.EVENT_FULL: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Sự kiện đã hết chỗ đăng ký",
    },

    ErrorCode.UNIT_NOT_ASSIGNED_TO_EVENT: {
        "status": status.HTTP_403_FORBIDDEN,
        "message": "Đơn vị của bạn không được giao sự kiện này",
    },
    ErrorCode.UNIT_EVENT_SUBMISSION_CLOSED: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Quá thời gian phản hồi",
    },
    ErrorCode.REPORT_LOCKED: {
        "status": status.HTTP_403_FORBIDDEN,
        "message": "Báo cáo đã khóa hoặc đã quá hạn nộp, không thể chỉnh sửa",
    },
    ErrorCode.EVENT_LOCKED: {
        "status": status.HTTP_403_FORBIDDEN,
        "message": "Sự kiện đã bị khóa, không thể thực hiện thao tác này",
    },
    ErrorCode.QR_PAYLOAD_INVALID: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Ma QR khong hop le",
    },
    ErrorCode.QR_SESSION_NOT_FOUND: {
        "status": status.HTTP_404_NOT_FOUND,
        "message": "Phien QR khong ton tai hoac da het han",
    },
    ErrorCode.QR_SESSION_CLOSED: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Phien QR da dong",
    },
    ErrorCode.QR_PAYLOAD_EXPIRED: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Ma QR da het han",
    },
    ErrorCode.LOCATION_REQUIRED: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Phien QR yeu cau vi tri check-in",
    },
    ErrorCode.LOCATION_OUT_OF_RANGE: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Ban dang o ngoai pham vi cho phep de check-in",
    },
    ErrorCode.DUPLICATE_CHECKIN: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Ban da quet check-in cho su kien nay roi",
    },
    ErrorCode.CHECKIN_QUEUE_UNAVAILABLE: {
        "status": status.HTTP_503_SERVICE_UNAVAILABLE,
        "message": "He thong xep hang check-in tam thoi khong kha dung",
    },
    ErrorCode.QR_SESSION_TOO_LARGE: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Phien QR qua dai, vuot qua gioi han cho phep",
    },
    ErrorCode.INVALID_QR_SESSION_TIME: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Thoi gian phien QR khong hop le",
    },
    ErrorCode.USER_NOT_ALLOWED_FOR_EVENT: {
        "status": status.HTTP_403_FORBIDDEN,
        "message": "Ban khong nam trong danh sach duoc phep check-in su kien nay",
    },
    ErrorCode.ATTENDANCE_CODE_INVALID: {
        "status": status.HTTP_400_BAD_REQUEST,
        "message": "Ma diem danh khong hop le hoac da het han",
    },
}


def app_exception(code: ErrorCode, extra_detail: Optional[str] = None) -> None:
    info = ERROR_DEFINITIONS[code]
    base_msg = info["message"]
    detail = f"{base_msg}: {extra_detail}" if extra_detail else base_msg
    raise HTTPException(status_code=info["status"], detail=detail)  # type: ignore[arg-type]
