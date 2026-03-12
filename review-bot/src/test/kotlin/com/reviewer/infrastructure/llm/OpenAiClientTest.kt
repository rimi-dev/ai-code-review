package com.reviewer.infrastructure.llm

import com.github.tomakehurst.wiremock.WireMockServer
import com.github.tomakehurst.wiremock.client.WireMock.aResponse
import com.github.tomakehurst.wiremock.client.WireMock.containing
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

class OpenAiClientTest {

    private lateinit var wireMockServer: WireMockServer
    private lateinit var client: OpenAiClient

    @BeforeEach
    fun setUp() {
        wireMockServer = WireMockServer(wireMockConfig().dynamicPort())
        wireMockServer.start()

        val properties = ProviderProperties(
            enabled = true,
            type = ProviderType.OPENAI,
            baseUrl = "http://localhost:${wireMockServer.port()}",
            apiKey = "test-openai-key",
            model = "gpt-4-turbo",
            temperature = 0.1,
            maxTokens = 4096,
        )

        client = OpenAiClient(
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
                post(urlEqualTo("/v1/chat/completions"))
                    .withHeader("Authorization", containing("Bearer test-openai-key"))
                    .willReturn(
                        aResponse()
                            .withStatus(200)
                            .withHeader("Content-Type", "application/json")
                            .withBody(
                                """
                                {
                                    "id": "chatcmpl-abc123",
                                    "model": "gpt-4-turbo",
                                    "choices": [
                                        {
                                            "index": 0,
                                            "message": {
                                                "role": "assistant",
                                                "content": "[{\"file\":\"src/App.kt\",\"line\":5,\"severity\":\"SUGGESTION\",\"category\":\"style\",\"title\":\"Style\",\"body\":\"Consider renaming\"}]"
                                            },
                                            "finish_reason": "stop"
                                        }
                                    ],
                                    "usage": {
                                        "prompt_tokens": 200,
                                        "completion_tokens": 100,
                                        "total_tokens": 300
                                    }
                                }
                                """.trimIndent(),
                            ),
                    ),
            )

            val result = client.generateReview("system prompt", "user prompt")

            assertEquals("openai", result.provider)
            assertEquals("gpt-4-turbo", result.model)
            assertEquals(200, result.inputTokens)
            assertEquals(100, result.outputTokens)
            assertEquals(300, result.totalTokens)
            assertTrue(result.content.contains("src/App.kt"))
        }

        @Test
        fun `should use correct provider name`() {
            assertEquals("openai", client.providerName)
        }
    }

    @Nested
    inner class ErrorResponses {

        @Test
        fun `should throw exception on 429 rate limit`() = runTest {
            wireMockServer.stubFor(
                post(urlEqualTo("/v1/chat/completions"))
                    .willReturn(
                        aResponse()
                            .withStatus(429)
                            .withHeader("Content-Type", "application/json")
                            .withBody(
                                """
                                {
                                    "error": {
                                        "message": "Rate limit reached",
                                        "type": "tokens",
                                        "code": "rate_limit_exceeded"
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
                post(urlEqualTo("/v1/chat/completions"))
                    .willReturn(
                        aResponse()
                            .withStatus(500)
                            .withHeader("Content-Type", "application/json")
                            .withBody(
                                """
                                {
                                    "error": {
                                        "message": "The server had an error",
                                        "type": "server_error"
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
        fun `should throw exception when response has no choices`() = runTest {
            wireMockServer.stubFor(
                post(urlEqualTo("/v1/chat/completions"))
                    .willReturn(
                        aResponse()
                            .withStatus(200)
                            .withHeader("Content-Type", "application/json")
                            .withBody(
                                """
                                {
                                    "id": "chatcmpl-empty",
                                    "model": "gpt-4-turbo",
                                    "choices": [],
                                    "usage": {
                                        "prompt_tokens": 100,
                                        "completion_tokens": 0,
                                        "total_tokens": 100
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

        @Test
        fun `should throw exception on 401 unauthorized`() = runTest {
            wireMockServer.stubFor(
                post(urlEqualTo("/v1/chat/completions"))
                    .willReturn(
                        aResponse()
                            .withStatus(401)
                            .withHeader("Content-Type", "application/json")
                            .withBody(
                                """
                                {
                                    "error": {
                                        "message": "Incorrect API key provided",
                                        "type": "invalid_request_error",
                                        "code": "invalid_api_key"
                                    }
                                }
                                """.trimIndent(),
                            ),
                    ),
            )

            val exception = assertThrows<WebClientResponseException> {
                client.generateReview("system prompt", "user prompt")
            }

            assertEquals(401, exception.statusCode.value())
        }
    }
}
