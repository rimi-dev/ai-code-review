package com.reviewer.api.dto.request

import com.reviewer.domain.model.ReviewStatus
import java.time.Instant

data class ReviewFilterRequest(
    val repositoryFullName: String? = null,
    val status: ReviewStatus? = null,
    val from: Instant? = null,
    val to: Instant? = null,
    val page: Int = 0,
    val size: Int = 20,
)
