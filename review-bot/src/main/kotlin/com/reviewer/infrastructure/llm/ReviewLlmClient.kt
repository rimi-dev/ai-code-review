package com.reviewer.infrastructure.llm

import com.reviewer.infrastructure.llm.dto.ReviewLlmResponse

interface ReviewLlmClient {
    val provider: String

    suspend fun generateReview(
        systemPrompt: String,
        userPrompt: String,
        maxTokens: Int = 4096,
    ): ReviewLlmResponse
}
