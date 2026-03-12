package com.reviewer.domain.model

import org.springframework.data.annotation.Id
import org.springframework.data.mongodb.core.mapping.Document
import java.time.Instant

@Document(collection = "repositories")
data class RegisteredRepository(
    @Id val id: String? = null,
    val platform: String = "GITHUB",
    val fullName: String,
    val owner: String,
    val name: String,
    val installationId: Long,
    val webhookSecret: String? = null,
    val accessToken: String? = null,
    val isActive: Boolean = true,
    val settings: RepositorySettings = RepositorySettings(),
    val reviewRules: List<ReviewRule> = emptyList(),
    val modelPreference: String = "auto",
    val createdAt: Instant? = null,
    val updatedAt: Instant? = null,
)

data class RepositorySettings(
    val autoReview: Boolean = true,
    val reviewOnDraft: Boolean = false,
    val maxDiffLines: Int = 3000,
    val maxFiles: Int = 50,
    val excludePatterns: List<String> = emptyList(),
    val language: String = "en",
    val customPrompt: String? = null,
)

data class ReviewRule(
    val pattern: String,
    val action: String = "REVIEW",
    val customPrompt: String? = null,
)
