package com.reviewer.infrastructure.llm

import com.reviewer.config.properties.ProviderProperties
import com.reviewer.infrastructure.llm.dto.ChatCompletionRequest
import com.reviewer.infrastructure.llm.dto.ChatCompletionResponse
import com.reviewer.infrastructure.llm.dto.ChatMessage
import com.reviewer.infrastructure.llm.dto.ReviewLlmResponse
import io.github.oshai.kotlinlogging.KotlinLogging
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.web.reactive.function.client.WebClient
import org.springframework.web.reactive.function.client.awaitBody

private val logger = KotlinLogging.logger {}

class OpenAiClient(
    webClientBuilder: WebClient.Builder,
    private val properties: ProviderProperties,
) : ReviewLlmClient {

    override val providerName: String = "openai"

    private val webClient: WebClient = webClientBuilder
        .baseUrl(properties.baseUrl)
        .defaultHeader(HttpHeaders.AUTHORIZATION, "Bearer ${properties.apiKey}")
        .defaultHeader(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
        .build()

    override suspend fun generateReview(
        systemPrompt: String,
        userPrompt: String,
        maxTokens: Int,
    ): ReviewLlmResponse {
        val request = ChatCompletionRequest(
            model = properties.model,
            messages = listOf(
                ChatMessage(role = "system", content = systemPrompt),
                ChatMessage(role = "user", content = userPrompt),
            ),
            temperature = properties.temperature,
            maxTokens = properties.maxTokens ?: maxTokens,
        )

        logger.debug { "Calling OpenAI API: model=${properties.model}" }

        val response = webClient.post()
            .uri("/v1/chat/completions")
            .bodyValue(request)
            .retrieve()
            .awaitBody<ChatCompletionResponse>()

        val content = response.choices.firstOrNull()?.message?.content
            ?: throw RuntimeException("No content in OpenAI response")

        val usage = response.usage

        return ReviewLlmResponse(
            content = content,
            model = response.model,
            provider = providerName,
            inputTokens = usage?.promptTokens ?: 0,
            outputTokens = usage?.completionTokens ?: 0,
            totalTokens = usage?.totalTokens ?: 0,
        )
    }
}
