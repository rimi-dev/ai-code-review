package com.reviewer.config.properties

import org.springframework.boot.context.properties.ConfigurationProperties
import java.time.Duration

@ConfigurationProperties(prefix = "review-bot.llm")
data class LlmProperties(
    val defaultProvider: String = "claude",
    val maxTokens: Int = 4096,
    val providers: Map<String, ProviderProperties> = emptyMap(),
)

data class ProviderProperties(
    val enabled: Boolean = true,
    val type: ProviderType,
    val baseUrl: String,
    val apiKey: String = "",
    val model: String,
    val timeout: Duration = Duration.ofSeconds(60),
    val maxTokens: Int? = null,
    val temperature: Double = 0.1,
    val apiVersion: String? = null,
    val fallbackTo: String? = null,
)

enum class ProviderType {
    CLAUDE, OPENAI, GEMINI
}
