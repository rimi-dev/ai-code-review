package com.reviewer.api.dto.response

data class ReviewStatsResponse(
    val totalReviews: Long,
    val completedReviews: Long,
    val failedReviews: Long,
    val skippedReviews: Long,
    val queuedReviews: Long,
    val totalComments: Long,
    val averageProcessingTimeMs: Double,
    val averageCommentsPerReview: Double,
)
