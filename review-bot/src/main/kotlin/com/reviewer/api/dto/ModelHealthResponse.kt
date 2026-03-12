package com.reviewer.api.dto

data class ModelHealthResponse(
    val providers: List<ProviderHealthStatus>,
)

data class ProviderHealthStatus(
    val name: String,
    val enabled: Boolean,
    val circuitBreakerState: String,
    val model: String,
)
