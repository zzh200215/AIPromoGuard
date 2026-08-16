"""统一错误码与业务异常（PRD §12）。"""

from typing import Any


class ErrorCode:
    SUCCESS = 0
    PARAM_ERROR = 1001
    FILE_TYPE_NOT_SUPPORTED = 1002
    FILE_TOO_LARGE = 1003
    UNAUTHORIZED = 1101          # 未认证 / 凭证无效
    FORBIDDEN = 1103             # 无权限
    TASK_NOT_FOUND = 2001
    TASK_INVALID_STATE = 2002
    RESULT_NOT_FOUND = 2003
    REGULATION_SEARCH_FAILED = 3001
    GRAPH_QUERY_FAILED = 3002
    LLM_CALL_FAILED = 4001
    LLM_OUTPUT_INVALID = 4002
    RULE_ENGINE_ERROR = 5001
    SOURCE_FETCH_FAILED = 6001    # 监管源抓取失败
    REGULATION_UPDATE_NOT_FOUND = 6002
    UPDATE_NOT_PENDING = 6003     # 监管动态记录状态不允许该操作
    INTERNAL_ERROR = 9001


ERROR_MESSAGES: dict[int, str] = {
    ErrorCode.SUCCESS: "成功",
    ErrorCode.PARAM_ERROR: "参数错误",
    ErrorCode.FILE_TYPE_NOT_SUPPORTED: "文件格式不支持",
    ErrorCode.FILE_TOO_LARGE: "文件过大",
    ErrorCode.UNAUTHORIZED: "未认证或登录已过期",
    ErrorCode.FORBIDDEN: "无权限执行该操作",
    ErrorCode.TASK_NOT_FOUND: "任务不存在",
    ErrorCode.TASK_INVALID_STATE: "任务状态非法",
    ErrorCode.RESULT_NOT_FOUND: "审查结果不存在",
    ErrorCode.REGULATION_SEARCH_FAILED: "法规检索失败",
    ErrorCode.GRAPH_QUERY_FAILED: "知识图谱查询失败",
    ErrorCode.LLM_CALL_FAILED: "LLM 调用失败",
    ErrorCode.LLM_OUTPUT_INVALID: "LLM 输出格式错误",
    ErrorCode.RULE_ENGINE_ERROR: "规则引擎执行错误",
    ErrorCode.SOURCE_FETCH_FAILED: "监管源抓取失败",
    ErrorCode.REGULATION_UPDATE_NOT_FOUND: "监管动态记录不存在",
    ErrorCode.UPDATE_NOT_PENDING: "监管动态记录状态不允许该操作",
    ErrorCode.INTERNAL_ERROR: "系统内部错误",
}

# 业务错误码对应的 HTTP 状态
HTTP_STATUS: dict[int, int] = {
    ErrorCode.PARAM_ERROR: 400,
    ErrorCode.FILE_TYPE_NOT_SUPPORTED: 400,
    ErrorCode.FILE_TOO_LARGE: 413,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.TASK_NOT_FOUND: 404,
    ErrorCode.TASK_INVALID_STATE: 409,
    ErrorCode.RESULT_NOT_FOUND: 404,
    ErrorCode.REGULATION_SEARCH_FAILED: 502,
    ErrorCode.GRAPH_QUERY_FAILED: 502,
    ErrorCode.LLM_CALL_FAILED: 502,
    ErrorCode.LLM_OUTPUT_INVALID: 502,
    ErrorCode.RULE_ENGINE_ERROR: 500,
    ErrorCode.SOURCE_FETCH_FAILED: 502,
    ErrorCode.REGULATION_UPDATE_NOT_FOUND: 404,
    ErrorCode.UPDATE_NOT_PENDING: 409,
    ErrorCode.INTERNAL_ERROR: 500,
}


class AppError(Exception):
    """业务异常：携带业务错误码与可选的附加数据。"""

    def __init__(
        self,
        code: int,
        message: str | None = None,
        http_status: int | None = None,
        data: Any = None,
    ) -> None:
        self.code = code
        self.message = message or ERROR_MESSAGES.get(code, "未知错误")
        self.http_status = http_status or HTTP_STATUS.get(code, 500)
        self.data = data
        super().__init__(self.message)
