package com.reviewer.api.dto.response

data class ErrorResponse(
    val error: ErrorDetail,
)

data class ErrorDetail(
    val message: String,
    val type: String,
    val param: String? = null,
    val code: String? = null,
)
