package com.reviewer.infrastructure.llm

import com.reviewer.api.exception.ApiException
import com.reviewer.config.properties.LlmProperties
import com.reviewer.infrastructure.llm.dto.ChatCompletionRequest
import com.reviewer.infrastructure.llm.dto.ChatCompletionResponse
import com.reviewer.infrastructure.llm.dto.ChatMessage
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
class VllmClient(
    webClientBuilder: WebClient.Builder,
    private val llmProperties: LlmProperties,
) : ReviewLlmClient {

    override val provider: String = "vllm"

    private val webClient: WebClient = webClientBuilder
        .baseUrl(llmProperties.vllmBaseUrl)
        .build()

    override suspend fun generateReview(
        systemPrompt: String,
        userPrompt: String,
        maxTokens: Int,
    ): ReviewLlmResponse {
        val request = ChatCompletionRequest(
            model = llmProperties.vllmModel,
            messages = listOf(
                ChatMessage(role = "system", content = systemPrompt),
                ChatMessage(role = "user", content = userPrompt),
            ),
            temperature = 0.1,
            maxTokens = maxTokens,
            stream = false,
        )

        logger.debug { "Sending vLLM request for model: ${llmProperties.vllmModel}" }

        val response = webClient.post()
            .uri("/v1/chat/completions")
            .contentType(MediaType.APPLICATION_JSON)
            .bodyValue(request)
            .retrieve()
            .onStatus({ it.isError }) { clientResponse ->
                clientResponse.bodyToMono<String>().map { body ->
                    logger.error { "vLLM API error: ${clientResponse.statusCode()} - $body" }
                    ApiException(
                        status = HttpStatus.valueOf(clientResponse.statusCode().value()),
                        message = "vLLM API error: $body",
                        errorCode = "llm_provider_error",
                    )
                }
            }
            .bodyToMono<ChatCompletionResponse>()
            .awaitSingle()

        val content = response.choices.firstOrNull()?.message?.content
            ?: throw ApiException(
                status = HttpStatus.INTERNAL_SERVER_ERROR,
                message = "vLLM returned empty response",
                errorCode = "llm_empty_response",
            )

        return ReviewLlmResponse(
            content = content,
            model = response.model,
            provider = provider,
            inputTokens = response.usage?.promptTokens ?: 0,
            outputTokens = response.usage?.completionTokens ?: 0,
            totalTokens = response.usage?.totalTokens ?: 0,
        )
    }
}
