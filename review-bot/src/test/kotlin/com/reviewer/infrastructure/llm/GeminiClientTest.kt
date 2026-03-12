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

class GeminiClientTest {

    private lateinit var wireMockServer: WireMockServer
    private lateinit var client: GeminiClient

    @BeforeEach
    fun setUp() {
        wireMockServer = WireMockServer(wireMockConfig().dynamicPort())
        wireMockServer.start()

        val properties = ProviderProperties(
            enabled = true,
            type = ProviderType.GEMINI,
            baseUrl = "http://localhost:${wireMockServer.port()}",
            apiKey = "test-gemini-key",
            model = "gemini-1.5-pro",
            temperature = 0.1,
            maxTokens = 4096,
        )

        client = GeminiClient(
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
                post(urlEqualTo("/v1beta/models/gemini-1.5-pro:generateContent"))
                    .withHeader("x-goog-api-key", equalTo("test-gemini-key"))
                    .willReturn(
                        aResponse()
                            .withStatus(200)
                            .withHeader("Content-Type", "application/json")
                            .withBody(
                                """
                                {
                                    "candidates": [
                                        {
                                            "content": {
                                                "role": "model",
                                                "parts": [
                                                    {
                                                        "text": "[{\"file\":\"src/App.kt\",\"line\":3,\"severity\":\"CRITICAL\",\"category\":\"security\",\"title\":\"SQL Injection\",\"body\":\"Unsafe query\"}]"
                                                    }
                                                ]
                                            },
                                            "finishReason": "STOP"
                                        }
                                    ],
                                    "usageMetadata": {
                                        "promptTokenCount": 250,
                                        "candidatesTokenCount": 120,
                                        "totalTokenCount": 370
                                    }
                                }
                                """.trimIndent(),
                            ),
                    ),
            )

            val result = client.generateReview("system prompt", "user prompt")

            assertEquals("gemini", result.provider)
            assertEquals("gemini-1.5-pro", result.model)
            assertEquals(250, result.inputTokens)
            assertEquals(120, result.outputTokens)
            assertEquals(370, result.totalTokens)
            assertTrue(result.content.contains("SQL Injection"))
        }

        @Test
        fun `should use correct provider name`() {
            assertEquals("gemini", client.providerName)
        }
    }

    @Nested
    inner class ErrorResponses {

        @Test
        fun `should throw exception on 429 rate limit`() = runTest {
            wireMockServer.stubFor(
                post(urlEqualTo("/v1beta/models/gemini-1.5-pro:generateContent"))
                    .willReturn(
                        aResponse()
                            .withStatus(429)
                            .withHeader("Content-Type", "application/json")
                            .withBody(
                                """
                                {
                                    "error": {
                                        "code": 429,
                                        "message": "Resource has been exhausted",
                                        "status": "RESOURCE_EXHAUSTED"
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
                post(urlEqualTo("/v1beta/models/gemini-1.5-pro:generateContent"))
                    .willReturn(
                        aResponse()
                            .withStatus(500)
                            .withHeader("Content-Type", "application/json")
                            .withBody(
                                """
                                {
                                    "error": {
                                        "code": 500,
                                        "message": "Internal error encountered",
                                        "status": "INTERNAL"
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
        fun `should throw exception when response has no candidates`() = runTest {
            wireMockServer.stubFor(
                post(urlEqualTo("/v1beta/models/gemini-1.5-pro:generateContent"))
                    .willReturn(
                        aResponse()
                            .withStatus(200)
                            .withHeader("Content-Type", "application/json")
                            .withBody(
                                """
                                {
                                    "candidates": [],
                                    "usageMetadata": {
                                        "promptTokenCount": 100,
                                        "candidatesTokenCount": 0,
                                        "totalTokenCount": 100
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
        fun `should throw exception on 403 forbidden`() = runTest {
            wireMockServer.stubFor(
                post(urlEqualTo("/v1beta/models/gemini-1.5-pro:generateContent"))
                    .willReturn(
                        aResponse()
                            .withStatus(403)
                            .withHeader("Content-Type", "application/json")
                            .withBody(
                                """
                                {
                                    "error": {
                                        "code": 403,
                                        "message": "The caller does not have permission",
                                        "status": "PERMISSION_DENIED"
                                    }
                                }
                                """.trimIndent(),
                            ),
                    ),
            )

            val exception = assertThrows<WebClientResponseException> {
                client.generateReview("system prompt", "user prompt")
            }

            assertEquals(403, exception.statusCode.value())
        }
    }
}
