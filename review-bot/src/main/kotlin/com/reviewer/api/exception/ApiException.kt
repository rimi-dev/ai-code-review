package com.reviewer.api.exception

import org.springframework.http.HttpStatus

class ApiException(
    val status: HttpStatus,
    override val message: String,
    val code: String? = null,
) : RuntimeException(message)
