package com.reviewer.config.properties

import org.springframework.boot.context.properties.ConfigurationProperties

@ConfigurationProperties(prefix = "review-bot.review")
data class ReviewProperties(
    val maxDiffLines: Int = 3000,
    val maxFiles: Int = 50,
    val excludePatterns: List<String> = listOf(
        "*.lock",
        "*.min.js",
        "*.min.css",
        "*.map",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "go.sum",
        "*.pb.go",
        "*.generated.*",
    ),
    val contextLines: Int = 3,
    val streamKey: String = "review-queue",
    val consumerGroup: String = "review-workers",
    val consumerName: String = "worker-1",
)
