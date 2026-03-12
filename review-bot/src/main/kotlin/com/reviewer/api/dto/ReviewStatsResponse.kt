package com.reviewer.api.dto

data class ReviewStatsResponse(
    val totalReviews: Long,
    val completedReviews: Long,
    val failedReviews: Long,
    val byProvider: Map<String, Long>,
    val byCategory: Map<String, Long>,
    val avgLatencyMs: Double,
)
