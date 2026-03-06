package com.reviewer.infrastructure.llm

import com.reviewer.infrastructure.llm.dto.ReviewLlmResponse
import com.reviewer.infrastructure.metrics.ReviewMetrics
import io.github.oshai.kotlinlogging.KotlinLogging
import io.github.resilience4j.circuitbreaker.CircuitBreaker
import io.github.resilience4j.kotlin.circuitbreaker.executeSuspendFunction
import org.springframework.stereotype.Component

private val logger = KotlinLogging.logger {}

@Component
class ReviewLlmClientFactory(
    private val vllmClient: VllmClient,
    private val claudeReviewClient: ClaudeReviewClient,
    private val vllmCircuitBreaker: CircuitBreaker,
    private val reviewMetrics: ReviewMetrics,
) {

    suspend fun generateReview(
        systemPrompt: String,
        userPrompt: String,
        maxTokens: Int = 4096,
    ): ReviewLlmResponse {
        return try {
            val response = vllmCircuitBreaker.executeSuspendFunction {
                logger.info { "Attempting review with primary LLM (vLLM)" }
                vllmClient.generateReview(systemPrompt, userPrompt, maxTokens)
            }
            reviewMetrics.recordLlmCall(response.provider, success = true)
            response
        } catch (e: Exception) {
            logger.warn(e) { "vLLM call failed, falling back to Claude: ${e.message}" }
            reviewMetrics.recordLlmCall("vllm", success = false)
            reviewMetrics.incrementFallbackCount()

            try {
                val fallbackResponse = claudeReviewClient.generateReview(
                    systemPrompt,
                    userPrompt,
                    maxTokens,
                )
                reviewMetrics.recordLlmCall(fallbackResponse.provider, success = true)
                fallbackResponse
            } catch (fallbackEx: Exception) {
                logger.error(fallbackEx) { "Claude fallback also failed: ${fallbackEx.message}" }
                reviewMetrics.recordLlmCall("claude", success = false)
                throw fallbackEx
            }
        }
    }
}
