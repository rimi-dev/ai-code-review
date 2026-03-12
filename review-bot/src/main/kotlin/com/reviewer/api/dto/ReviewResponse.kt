package com.reviewer.api.dto

import com.reviewer.domain.model.ReviewRequest
import com.reviewer.domain.model.ReviewResult
import java.time.Instant

data class ReviewResponse(
    val id: String,
    val repositoryFullName: String,
    val platformPrId: Int,
    val title: String,
    val author: String,
    val status: String,
    val reviews: List<ReviewResult>,
    val createdAt: Instant?,
) {
    companion object {
        fun from(req: ReviewRequest) = ReviewResponse(
            id = req.id!!,
            repositoryFullName = req.repositoryFullName,
            platformPrId = req.platformPrId,
            title = req.title,
            author = req.author,
            status = req.status.name,
            reviews = req.reviews,
            createdAt = req.createdAt,
        )
    }
}
