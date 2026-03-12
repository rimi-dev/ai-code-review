package com.reviewer.infrastructure.llm

import com.reviewer.config.properties.LlmProperties
import com.reviewer.config.properties.ProviderType
import com.reviewer.infrastructure.llm.dto.ReviewLlmResponse
import io.github.oshai.kotlinlogging.KotlinLogging
import io.github.resilience4j.circuitbreaker.CircuitBreaker
import io.github.resilience4j.circuitbreaker.CircuitBreakerConfig
import io.github.resilience4j.circuitbreaker.CircuitBreakerRegistry
import io.github.resilience4j.kotlin.circuitbreaker.executeSuspendFunction
import jakarta.annotation.PostConstruct
import org.springframework.stereotype.Component
import org.springframework.web.reactive.function.client.WebClient
import java.time.Duration

private val logger = KotlinLogging.logger {}

@Component
class ReviewLlmClientFactory(
    private val webClientBuilder: WebClient.Builder,
    private val llmProperties: LlmProperties,
    private val circuitBreakerRegistry: CircuitBreakerRegistry,
) {

    private val clients = mutableMapOf<String, ReviewLlmClient>()
    private val circuitBreakers = mutableMapOf<String, CircuitBreaker>()

    @PostConstruct
    fun initialize() {
        llmProperties.providers.forEach { (name, props) ->
            if (!props.enabled) {
                logger.info { "LLM provider '$name' is disabled, skipping" }
                return@forEach
            }

            val client: ReviewLlmClient = when (props.type) {
                ProviderType.CLAUDE -> ClaudeReviewClient(webClientBuilder, props)
                ProviderType.OPENAI -> OpenAiClient(webClientBuilder, props)
                ProviderType.GEMINI -> GeminiClient(webClientBuilder, props)
            }
            clients[name] = client

            val cbConfig = CircuitBreakerConfig.custom()
                .failureRateThreshold(50f)
                .slowCallRateThreshold(80f)
                .slowCallDurationThreshold(Duration.ofSeconds(30))
                .slidingWindowType(CircuitBreakerConfig.SlidingWindowType.COUNT_BASED)
                .slidingWindowSize(20)
                .waitDurationInOpenState(Duration.ofSeconds(60))
                .permittedNumberOfCallsInHalfOpenState(5)
                .minimumNumberOfCalls(10)
                .build()
            circuitBreakers[name] = circuitBreakerRegistry.circuitBreaker("llm-$name", cbConfig)

            logger.info { "Registered LLM provider: $name (${props.type}, model=${props.model})" }
        }

        if (clients.isEmpty()) {
            throw IllegalStateException("No LLM providers are enabled")
        }
    }

    suspend fun generateReview(
        systemPrompt: String,
        userPrompt: String,
        maxTokens: Int = llmProperties.maxTokens,
        preferredProvider: String? = null,
    ): ReviewLlmResponse {
        val startProvider = preferredProvider?.takeIf { it != "auto" } ?: llmProperties.defaultProvider
        return executeWithFallback(startProvider, systemPrompt, userPrompt, maxTokens, mutableSetOf())
    }

    private suspend fun executeWithFallback(
        providerName: String,
        systemPrompt: String,
        userPrompt: String,
        maxTokens: Int,
        attempted: MutableSet<String>,
    ): ReviewLlmResponse {
        if (providerName in attempted) {
            throw RuntimeException("All LLM providers failed. Attempted: $attempted")
        }
        attempted.add(providerName)

        val client = clients[providerName]
            ?: throw RuntimeException("LLM provider '$providerName' not found. Available: ${clients.keys}")
        val cb = circuitBreakers[providerName]!!
        val providerProps = llmProperties.providers[providerName]!!

        return try {
            cb.executeSuspendFunction {
                logger.info { "Calling LLM provider: $providerName" }
                client.generateReview(systemPrompt, userPrompt, maxTokens)
            }
        } catch (e: Exception) {
            logger.warn(e) { "LLM provider '$providerName' failed" }

            val fallbackTo = providerProps.fallbackTo
            if (fallbackTo != null && fallbackTo !in attempted) {
                logger.info { "Falling back from '$providerName' to '$fallbackTo'" }
                val response = executeWithFallback(fallbackTo, systemPrompt, userPrompt, maxTokens, attempted)
                response.copy(provider = "${response.provider} (fallback from $providerName)")
            } else {
                throw RuntimeException("LLM provider '$providerName' failed and no fallback available", e)
            }
        }
    }

    fun getCircuitBreakerState(providerName: String): CircuitBreaker.State? {
        return circuitBreakers[providerName]?.state
    }

    fun getAvailableProviders(): Set<String> = clients.keys
}
