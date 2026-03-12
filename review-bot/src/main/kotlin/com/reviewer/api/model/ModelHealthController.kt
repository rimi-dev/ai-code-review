package com.reviewer.api.model

import com.reviewer.api.dto.ModelHealthResponse
import com.reviewer.api.dto.ProviderHealthStatus
import com.reviewer.config.properties.LlmProperties
import com.reviewer.infrastructure.llm.ReviewLlmClientFactory
import org.springframework.web.bind.annotation.GetMapping
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/v1/models")
class ModelHealthController(
    private val llmProperties: LlmProperties,
    private val llmClientFactory: ReviewLlmClientFactory,
) {
    @GetMapping("/health")
    suspend fun health(): ModelHealthResponse {
        val providers = llmProperties.providers.map { (name, props) ->
            ProviderHealthStatus(
                name = name,
                enabled = props.enabled,
                circuitBreakerState = llmClientFactory.getCircuitBreakerState(name)?.name ?: "UNKNOWN",
                model = props.model,
            )
        }
        return ModelHealthResponse(providers = providers)
    }
}
