package com.reviewer.config.properties

import org.springframework.boot.context.properties.ConfigurationProperties
import java.time.Duration

@ConfigurationProperties(prefix = "review-bot.llm")
data class LlmProperties(
    val vllmBaseUrl: String = "http://localhost:8000",
    val vllmModel: String = "default",
    val vllmTimeout: Duration = Duration.ofSeconds(120),
    val claudeBaseUrl: String = "https://api.anthropic.com",
    val claudeApiKey: String = "",
    val claudeModel: String = "claude-sonnet-4-20250514",
    val claudeApiVersion: String = "2024-01-01",
    val claudeTimeout: Duration = Duration.ofSeconds(60),
    val maxTokens: Int = 4096,
)
