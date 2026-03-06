package com.reviewer.infrastructure.llm

import com.reviewer.api.exception.ApiException
import com.reviewer.config.properties.LlmProperties
import com.reviewer.infrastructure.llm.dto.ClaudeMessage
import com.reviewer.infrastructure.llm.dto.ClaudeMessagesRequest
import com.reviewer.infrastructure.llm.dto.ClaudeMessagesResponse
import com.reviewer.infrastructure.llm.dto.ReviewLlmResponse
import io.github.oshai.kotlinlogging.KotlinLogging
import kotlinx.coroutines.reactor.awaitSingle
import org.springframework.http.HttpStatus
import org.springframework.http.MediaType
import org.springframework.stereotype.Component
import org.springframework.web.reactive.function.client.WebClient
import org.springframework.web.reactive.function.client.bodyToMono

private val logger = KotlinLogging.logger {}

@Component
class ClaudeReviewClient(
    webClientBuilder: WebClient.Builder,
    private val llmProperties: LlmProperties,
) : ReviewLlmClient {

    override val provider: String = "claude"

    private val webClient: WebClient = webClientBuilder
        .baseUrl(llmProperties.claudeBaseUrl)
        .build()

    override suspend fun generateReview(
        systemPrompt: String,
        userPrompt: String,
        maxTokens: Int,
    ): ReviewLlmResponse {
        val request = ClaudeMessagesRequest(
            model = llmProperties.claudeModel,
            maxTokens = maxTokens,
            system = systemPrompt,
            messages = listOf(
                ClaudeMessage(role = "user", content = userPrompt),
            ),
            temperature = 0.1,
            stream = false,
        )

        logger.debug { "Sending Claude review request for model: ${llmProperties.claudeModel}" }

        val response = webClient.post()
            .uri("/v1/messages")
            .header("x-api-key", llmProperties.claudeApiKey)
            .header("anthropic-version", llmProperties.claudeApiVersion)
            .contentType(MediaType.APPLICATION_JSON)
            .bodyValue(request)
            .retrieve()
            .onStatus({ it.isError }) { clientResponse ->
                clientResponse.bodyToMono<String>().map { body ->
                    logger.error { "Claude API error: ${clientResponse.statusCode()} - $body" }
                    ApiException(
                        status = HttpStatus.valueOf(clientResponse.statusCode().value()),
                        message = "Claude API error: $body",
                        errorCode = "llm_provider_error",
                    )
                }
            }
            .bodyToMono<ClaudeMessagesResponse>()
            .awaitSingle()

        val content = response.content
            .firstOrNull { it.type == "text" }
            ?.text
            ?: throw ApiException(
                status = HttpStatus.INTERNAL_SERVER_ERROR,
                message = "Claude returned empty response",
                errorCode = "llm_empty_response",
            )

        return ReviewLlmResponse(
            content = content,
            model = response.model,
            provider = provider,
            inputTokens = response.usage.inputTokens,
            outputTokens = response.usage.outputTokens,
            totalTokens = response.usage.inputTokens + response.usage.outputTokens,
        )
    }
}
