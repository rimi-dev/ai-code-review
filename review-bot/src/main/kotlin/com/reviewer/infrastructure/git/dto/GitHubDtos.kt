package com.reviewer.infrastructure.git.dto

import java.time.Instant

// --- Webhook Payload ---

data class WebhookPayload(
    val action: String,
    val number: Int? = null,
    val pullRequest: PullRequestPayload? = null,
    val repository: RepositoryPayload? = null,
    val installation: InstallationPayload? = null,
    val sender: SenderPayload? = null,
)

data class PullRequestPayload(
    val id: Long,
    val number: Int,
    val title: String,
    val body: String? = null,
    val state: String,
    val draft: Boolean = false,
    val htmlUrl: String,
    val diffUrl: String,
    val head: BranchRef,
    val base: BranchRef,
    val user: SenderPayload,
    val changedFiles: Int? = null,
    val additions: Int? = null,
    val deletions: Int? = null,
)

data class BranchRef(
    val ref: String,
    val sha: String,
    val repo: RepositoryPayload? = null,
)

data class RepositoryPayload(
    val id: Long,
    val fullName: String,
    val name: String,
    val owner: OwnerPayload,
    val private: Boolean = false,
)

data class OwnerPayload(
    val login: String,
    val id: Long? = null,
)

data class InstallationPayload(
    val id: Long,
)

data class SenderPayload(
    val login: String,
    val id: Long? = null,
)

// --- PR Detail ---

data class PrDetail(
    val number: Int,
    val title: String,
    val body: String? = null,
    val state: String,
    val draft: Boolean = false,
    val htmlUrl: String,
    val diffUrl: String,
    val head: BranchRef,
    val base: BranchRef,
    val user: SenderPayload,
    val changedFiles: Int = 0,
    val additions: Int = 0,
    val deletions: Int = 0,
)

// --- PR File ---

data class PrFile(
    val sha: String,
    val filename: String,
    val status: String,
    val additions: Int = 0,
    val deletions: Int = 0,
    val changes: Int = 0,
    val patch: String? = null,
    val blobUrl: String? = null,
    val rawUrl: String? = null,
    val contentsUrl: String? = null,
)

// --- Create Review ---

data class CreateReviewRequest(
    val commitId: String,
    val body: String,
    val event: String = "COMMENT",
    val comments: List<CreateReviewCommentItem> = emptyList(),
)

data class CreateReviewCommentItem(
    val path: String,
    val line: Int? = null,
    val side: String? = "RIGHT",
    val body: String,
)

data class CreateReviewResponse(
    val id: Long,
    val body: String? = null,
    val state: String? = null,
    val htmlUrl: String? = null,
)

// --- Installation Token ---

data class InstallationTokenResponse(
    val token: String,
    val expiresAt: Instant? = null,
)
