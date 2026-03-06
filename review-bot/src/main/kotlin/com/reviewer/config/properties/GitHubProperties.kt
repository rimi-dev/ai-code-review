package com.reviewer.config.properties

import org.springframework.boot.context.properties.ConfigurationProperties

@ConfigurationProperties(prefix = "review-bot.github")
data class GitHubProperties(
    val webhookSecret: String,
    val appId: String,
    val privateKeyPath: String,
    val apiBaseUrl: String = "https://api.github.com",
)
