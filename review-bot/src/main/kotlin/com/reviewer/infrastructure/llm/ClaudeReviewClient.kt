package com.reviewer.infrastructure.llm

import com.reviewer.config.properties.ProviderProperties
import com.reviewer.infrastructure.llm.dto.ClaudeMessage
import com.reviewer.infrastructure.llm.dto.ClaudeMessagesRequest
import com.reviewer.infrastructure.llm.dto.ClaudeMessagesResponse
import com.reviewer.infrastructure.llm.dto.ReviewLlmResponse
import io.github.oshai.kotlinlogging.KotlinLogging
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.web.reactive.function.client.WebClient
import org.springframework.web.reactive.function.client.awaitBody

private val logger = KotlinLogging.logger {}

class ClaudeReviewClient(
    webClientBuilder: WebClient.Builder,
    private val properties: ProviderProperties,
) : ReviewLlmClient {

    override val providerName: String = "claude"

    private val webClient: WebClient = webClientBuilder
        .baseUrl(properties.baseUrl)
        .defaultHeader("x-api-key", properties.apiKey)
        .defaultHeader("anthropic-version", properties.apiVersion ?: "2024-01-01")
        .defaultHeader(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
        .build()

    override suspend fun generateReview(
        systemPrompt: String,
        userPrompt: String,
        maxTokens: Int,
    ): ReviewLlmResponse {
        val request = ClaudeMessagesRequest(
            model = properties.model,
            maxTokens = properties.maxTokens ?: maxTokens,
            system = systemPrompt,
            messages = listOf(ClaudeMessage(role = "user", content = userPrompt)),
            temperature = properties.temperature,
        )

        logger.debug { "Calling Claude API: model=${properties.model}" }

        val response = webClient.post()
            .uri("/v1/messages")
            .bodyValue(request)
            .retrieve()
            .awaitBody<ClaudeMessagesResponse>()

        val content = response.content
            .firstOrNull { it.type == "text" }?.text
            ?: throw RuntimeException("No text content in Claude response")

        return ReviewLlmResponse(
            content = content,
            model = response.model,
            provider = providerName,
            inputTokens = response.usage.inputTokens,
            outputTokens = response.usage.outputTokens,
            totalTokens = response.usage.inputTokens + response.usage.outputTokens,
        )
    }
}
