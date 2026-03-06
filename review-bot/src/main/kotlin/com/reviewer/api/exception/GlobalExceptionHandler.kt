package com.reviewer.api.exception

import com.reviewer.api.dto.response.ErrorDetail
import com.reviewer.api.dto.response.ErrorResponse
import io.github.oshai.kotlinlogging.KotlinLogging
import org.springframework.http.HttpStatus
import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.ControllerAdvice
import org.springframework.web.bind.annotation.ExceptionHandler
import org.springframework.web.server.ServerWebInputException

private val logger = KotlinLogging.logger {}

@ControllerAdvice
class GlobalExceptionHandler {

    @ExceptionHandler(ApiException::class)
    fun handleApiException(ex: ApiException): ResponseEntity<ErrorResponse> {
        logger.warn { "API exception: ${ex.status} - ${ex.message}" }

        val errorResponse = ErrorResponse(
            error = ErrorDetail(
                message = ex.message,
                type = mapStatusToType(ex.status),
                code = ex.errorCode,
            ),
        )
        return ResponseEntity.status(ex.status).body(errorResponse)
    }

    @ExceptionHandler(ServerWebInputException::class)
    fun handleInputException(ex: ServerWebInputException): ResponseEntity<ErrorResponse> {
        logger.warn { "Input validation error: ${ex.message}" }

        val errorResponse = ErrorResponse(
            error = ErrorDetail(
                message = ex.message,
                type = "invalid_request_error",
                code = "invalid_request",
            ),
        )
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(errorResponse)
    }

    @ExceptionHandler(Exception::class)
    fun handleGenericException(ex: Exception): ResponseEntity<ErrorResponse> {
        logger.error(ex) { "Unexpected error: ${ex.message}" }

        val errorResponse = ErrorResponse(
            error = ErrorDetail(
                message = "Internal server error",
                type = "server_error",
                code = "internal_error",
            ),
        )
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(errorResponse)
    }

    private fun mapStatusToType(status: HttpStatus): String {
        return when {
            status == HttpStatus.UNAUTHORIZED -> "authentication_error"
            status == HttpStatus.FORBIDDEN -> "permission_error"
            status == HttpStatus.TOO_MANY_REQUESTS -> "rate_limit_error"
            status == HttpStatus.NOT_FOUND -> "not_found_error"
            status.is4xxClientError -> "invalid_request_error"
            status.is5xxServerError -> "server_error"
            else -> "api_error"
        }
    }
}
