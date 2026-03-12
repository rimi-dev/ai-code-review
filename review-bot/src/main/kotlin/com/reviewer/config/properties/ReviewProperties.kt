package com.reviewer.config.properties

import org.springframework.boot.context.properties.ConfigurationProperties

@ConfigurationProperties(prefix = "review-bot.review")
data class ReviewProperties(
    val maxDiffLines: Int = 3000,
    val maxFiles: Int = 50,
    val contextLines: Int = 5,
    val excludePatterns: List<String> = emptyList(),
)
