package com.reviewer.infrastructure.llm

import com.github.tomakehurst.wiremock.WireMockServer
import com.github.tomakehurst.wiremock.client.WireMock.aResponse
import com.github.tomakehurst.wiremock.client.WireMock.equalTo
import com.github.tomakehurst.wiremock.client.WireMock.post
import com.github.tomakehurst.wiremock.client.WireMock.urlEqualTo
import com.github.tomakehurst.wiremock.core.WireMockConfiguration.wireMockConfig
import com.reviewer.config.properties.ProviderProperties
import com.reviewer.config.properties.ProviderType
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.AfterEach
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.BeforeEach
import org.junit.jupiter.api.Nested
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows
import org.springframework.web.reactive.function.client.WebClient
import org.springframework.web.reactive.function.client.WebClientResponseException

class ClaudeReviewClientTest {

    private lateinit var wireMockServer: WireMockServer
    private lateinit var client: ClaudeReviewClient

    @BeforeEach
    fun setUp() {
        wireMockServer = WireMockServer(wireMockConfig().dynamicPort())
        wireMockServer.start()

        val properties = ProviderProperties(
            enabled = true,
            type = ProviderType.CLAUDE,
            baseUrl = "http://localhost:${wireMockServer.port()}",
            apiKey = "test-api-key",
            model = "claude-3-opus-20240229",
            temperature = 0.1,
            maxTokens = 4096,
            apiVersion = "2024-01-01",
        )

        client = ClaudeReviewClient(
            webClientBuilder = WebClient.builder(),
            properties = properties,
        )
    }

    @AfterEach
    fun tearDown() {
        wireMockServer.stop()
    }

    @Nested
    inner class SuccessfulResponse {

        @Test
        fun `should return parsed response on success`() = runTest {
            wireMockServer.stubFor(
                post(urlEqualTo("/v1/messages"))
                    .withHeader("x-api-key", equalTo("test-api-key"))
                    .withHeader("anthropic-version", equalTo("2024-01-01"))
                    .willReturn(
                        aResponse()
                            .withStatus(200)
                            .withHeader("Content-Type", "application/json")
                            .withBody(
                                """
                                {
                                    "id": "msg_123",
                                    "type": "message",
                                    "role": "assistant",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": "[{\"file\":\"src/App.kt\",\"line\":1,\"severity\":\"WARNING\",\"category\":\"quality\",\"title\":\"Issue\",\"body\":\"Description\"}]"
                                        }
                                    ],
                                    "model": "claude-3-opus-20240229",
                                    "stop_reason": "end_turn",
                                    "usage": {
                                        "input_tokens": 150,
                                        "output_tokens": 80
                                    }
                                }
                                """.trimIndent(),
                            ),
                    ),
            )

            val result = client.generateReview("system prompt", "user prompt")

            assertEquals("claude", result.provider)
            assertEquals("claude-3-opus-20240229", result.model)
            assertEquals(150, result.inputTokens)
            assertEquals(80, result.outputTokens)
            assertEquals(230, result.totalTokens)
            assertTrue(result.content.contains("src/App.kt"))
        }

        @Test
        fun `should use correct provider name`() {
            assertEquals("claude", client.providerName)
        }
    }

    @Nested
    inner class ErrorResponses {

        @Test
        fun `should throw exception on 429 rate limit`() = runTest {
            wireMockServer.stubFor(
                post(urlEqualTo("/v1/messages"))
                    .willReturn(
                        aResponse()
                            .withStatus(429)
                            .withHeader("Content-Type", "application/json")
                            .withBody(
                                """
                                {
                                    "type": "error",
                                    "error": {
                                        "type": "rate_limit_error",
                                        "message": "Rate limit exceeded"
                                    }
                                }
                                """.trimIndent(),
                            ),
                    ),
            )

            val exception = assertThrows<WebClientResponseException> {
                client.generateReview("system prompt", "user prompt")
            }

            assertEquals(429, exception.statusCode.value())
        }

        @Test
        fun `should throw exception on 500 server error`() = runTest {
            wireMockServer.stubFor(
                post(urlEqualTo("/v1/messages"))
                    .willReturn(
                        aResponse()
                            .withStatus(500)
                            .withHeader("Content-Type", "application/json")
                            .withBody(
                                """
                                {
                                    "type": "error",
                                    "error": {
                                        "type": "api_error",
                                        "message": "Internal server error"
                                    }
                                }
                                """.trimIndent(),
                            ),
                    ),
            )

            val exception = assertThrows<WebClientResponseException> {
                client.generateReview("system prompt", "user prompt")
            }

            assertEquals(500, exception.statusCode.value())
        }

        @Test
        fun `should throw exception when response has no text content`() = runTest {
            wireMockServer.stubFor(
                post(urlEqualTo("/v1/messages"))
                    .willReturn(
                        aResponse()
                            .withStatus(200)
                            .withHeader("Content-Type", "application/json")
                            .withBody(
                                """
                                {
                                    "id": "msg_123",
                                    "type": "message",
                                    "role": "assistant",
                                    "content": [],
                                    "model": "claude-3-opus-20240229",
                                    "stop_reason": "end_turn",
                                    "usage": {
                                        "input_tokens": 100,
                                        "output_tokens": 0
                                    }
                                }
                                """.trimIndent(),
                            ),
                    ),
            )

            assertThrows<RuntimeException> {
                client.generateReview("system prompt", "user prompt")
            }
        }
    }
}
