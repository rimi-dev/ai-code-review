package com.reviewer.domain.model

import org.springframework.data.annotation.CreatedDate
import org.springframework.data.annotation.Id
import org.springframework.data.annotation.LastModifiedDate
import org.springframework.data.mongodb.core.index.Indexed
import org.springframework.data.mongodb.core.mapping.Document
import java.time.Instant

@Document(collection = "registered_repositories")
data class RegisteredRepository(
    @Id val id: String? = null,
    @Indexed(unique = true) val fullName: String,
    val owner: String,
    val name: String,
    val installationId: Long,
    val enabled: Boolean = true,
    val reviewConfig: ReviewConfig = ReviewConfig(),
    @CreatedDate val createdAt: Instant? = null,
    @LastModifiedDate val updatedAt: Instant? = null,
)

data class ReviewConfig(
    val autoReview: Boolean = true,
    val reviewOnDraft: Boolean = false,
    val maxDiffLines: Int? = null,
    val maxFiles: Int? = null,
    val excludePatterns: List<String> = emptyList(),
    val language: String = "en",
    val customPrompt: String? = null,
)
