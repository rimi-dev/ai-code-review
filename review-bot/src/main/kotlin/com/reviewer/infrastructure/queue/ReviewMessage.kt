package com.reviewer.infrastructure.queue

data class ReviewMessage(
    val reviewRequestId: String,
    val repositoryFullName: String,
    val pullRequestNumber: Int,
)
