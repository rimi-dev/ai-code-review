package com.reviewer.infrastructure.llm

import com.reviewer.config.properties.ProviderProperties
import com.reviewer.infrastructure.llm.dto.GeminiContent
import com.reviewer.infrastructure.llm.dto.GeminiGenerateRequest
import com.reviewer.infrastructure.llm.dto.GeminiGenerateResponse
import com.reviewer.infrastructure.llm.dto.GeminiGenerationConfig
import com.reviewer.infrastructure.llm.dto.GeminiPart
import com.reviewer.infrastructure.llm.dto.ReviewLlmResponse
import io.github.oshai.kotlinlogging.KotlinLogging
import org.springframework.http.HttpHeaders
import org.springframework.http.MediaType
import org.springframework.web.reactive.function.client.WebClient
import org.springframework.web.reactive.function.client.awaitBody

private val logger = KotlinLogging.logger {}

class GeminiClient(
    webClientBuilder: WebClient.Builder,
    private val properties: ProviderProperties,
) : ReviewLlmClient {

    override val providerName: String = "gemini"

    private val webClient: WebClient = webClientBuilder
        .baseUrl(properties.baseUrl)
        .defaultHeader("x-goog-api-key", properties.apiKey)
        .defaultHeader(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
        .build()

    override suspend fun generateReview(
        systemPrompt: String,
        userPrompt: String,
        maxTokens: Int,
    ): ReviewLlmResponse {
        val request = GeminiGenerateRequest(
            contents = listOf(
                GeminiContent(
                    role = "user",
                    parts = listOf(GeminiPart(text = userPrompt)),
                ),
            ),
            systemInstruction = GeminiContent(
                parts = listOf(GeminiPart(text = systemPrompt)),
            ),
            generationConfig = GeminiGenerationConfig(
                temperature = properties.temperature,
                maxOutputTokens = properties.maxTokens ?: maxTokens,
            ),
        )

        logger.debug { "Calling Gemini API: model=${properties.model}" }

        val response = webClient.post()
            .uri("/v1beta/models/${properties.model}:generateContent")
            .bodyValue(request)
            .retrieve()
            .awaitBody<GeminiGenerateResponse>()

        val content = response.candidates.firstOrNull()?.content?.parts?.firstOrNull()?.text
            ?: throw RuntimeException("No content in Gemini response")

        val usage = response.usageMetadata

        return ReviewLlmResponse(
            content = content,
            model = properties.model,
            provider = providerName,
            inputTokens = usage?.promptTokenCount ?: 0,
            outputTokens = usage?.candidatesTokenCount ?: 0,
            totalTokens = usage?.totalTokenCount ?: 0,
        )
    }
}
