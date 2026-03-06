package com.reviewer.infrastructure.git

import com.reviewer.api.exception.ApiException
import com.reviewer.config.properties.GitHubProperties
import com.reviewer.infrastructure.git.dto.CreateReviewRequest
import com.reviewer.infrastructure.git.dto.CreateReviewResponse
import com.reviewer.infrastructure.git.dto.PrDetail
import com.reviewer.infrastructure.git.dto.PrFile
import io.github.oshai.kotlinlogging.KotlinLogging
import kotlinx.coroutines.reactor.awaitSingle
import org.springframework.http.HttpStatus
import org.springframework.http.MediaType
import org.springframework.stereotype.Component
import org.springframework.web.reactive.function.client.WebClient
import org.springframework.web.reactive.function.client.bodyToMono

private val logger = KotlinLogging.logger {}

@Component
class GitHubApiClient(
    webClientBuilder: WebClient.Builder,
    private val gitHubProperties: GitHubProperties,
    private val tokenProvider: GitHubAppTokenProvider,
) {

    private val webClient: WebClient = webClientBuilder
        .baseUrl(gitHubProperties.apiBaseUrl)
        .build()

    suspend fun getPrDetail(
        owner: String,
        repo: String,
        prNumber: Int,
        installationId: Long,
    ): PrDetail {
        val token = tokenProvider.getInstallationToken(installationId)

        logger.debug { "Fetching PR detail: $owner/$repo#$prNumber" }

        return webClient.get()
            .uri("/repos/{owner}/{repo}/pulls/{prNumber}", owner, repo, prNumber)
            .header("Authorization", "token $token")
            .header("Accept", "application/vnd.github+json")
            .retrieve()
            .onStatus({ it.isError }) { clientResponse ->
                clientResponse.bodyToMono<String>().map { body ->
                    logger.error { "GitHub API error fetching PR: ${clientResponse.statusCode()} - $body" }
                    ApiException(
                        status = HttpStatus.valueOf(clientResponse.statusCode().value()),
                        message = "Failed to fetch PR detail: $body",
                        errorCode = "github_api_error",
                    )
                }
            }
            .bodyToMono<PrDetail>()
            .awaitSingle()
    }

    suspend fun getPrDiff(
        owner: String,
        repo: String,
        prNumber: Int,
        installationId: Long,
    ): String {
        val token = tokenProvider.getInstallationToken(installationId)

        logger.debug { "Fetching PR diff: $owner/$repo#$prNumber" }

        return webClient.get()
            .uri("/repos/{owner}/{repo}/pulls/{prNumber}", owner, repo, prNumber)
            .header("Authorization", "token $token")
            .header("Accept", "application/vnd.github.v3.diff")
            .retrieve()
            .onStatus({ it.isError }) { clientResponse ->
                clientResponse.bodyToMono<String>().map { body ->
                    logger.error { "GitHub API error fetching diff: ${clientResponse.statusCode()} - $body" }
                    ApiException(
                        status = HttpStatus.valueOf(clientResponse.statusCode().value()),
                        message = "Failed to fetch PR diff: $body",
                        errorCode = "github_api_error",
                    )
                }
            }
            .bodyToMono<String>()
            .awaitSingle()
    }

    suspend fun getPrFiles(
        owner: String,
        repo: String,
        prNumber: Int,
        installationId: Long,
    ): List<PrFile> {
        val token = tokenProvider.getInstallationToken(installationId)

        logger.debug { "Fetching PR files: $owner/$repo#$prNumber" }

        return webClient.get()
            .uri("/repos/{owner}/{repo}/pulls/{prNumber}/files?per_page=100", owner, repo, prNumber)
            .header("Authorization", "token $token")
            .header("Accept", "application/vnd.github+json")
            .retrieve()
            .onStatus({ it.isError }) { clientResponse ->
                clientResponse.bodyToMono<String>().map { body ->
                    logger.error { "GitHub API error fetching files: ${clientResponse.statusCode()} - $body" }
                    ApiException(
                        status = HttpStatus.valueOf(clientResponse.statusCode().value()),
                        message = "Failed to fetch PR files: $body",
                        errorCode = "github_api_error",
                    )
                }
            }
            .bodyToMono<List<PrFile>>()
            .awaitSingle()
    }

    suspend fun createPrReview(
        owner: String,
        repo: String,
        prNumber: Int,
        installationId: Long,
        reviewRequest: CreateReviewRequest,
    ): CreateReviewResponse {
        val token = tokenProvider.getInstallationToken(installationId)

        logger.debug { "Creating PR review: $owner/$repo#$prNumber with ${reviewRequest.comments.size} comments" }

        return webClient.post()
            .uri("/repos/{owner}/{repo}/pulls/{prNumber}/reviews", owner, repo, prNumber)
            .header("Authorization", "token $token")
            .header("Accept", "application/vnd.github+json")
            .contentType(MediaType.APPLICATION_JSON)
            .bodyValue(reviewRequest)
            .retrieve()
            .onStatus({ it.isError }) { clientResponse ->
                clientResponse.bodyToMono<String>().map { body ->
                    logger.error { "GitHub API error creating review: ${clientResponse.statusCode()} - $body" }
                    ApiException(
                        status = HttpStatus.valueOf(clientResponse.statusCode().value()),
                        message = "Failed to create PR review: $body",
                        errorCode = "github_api_error",
                    )
                }
            }
            .bodyToMono<CreateReviewResponse>()
            .awaitSingle()
    }

    suspend fun createReviewComment(
        owner: String,
        repo: String,
        prNumber: Int,
        installationId: Long,
        body: String,
        commitId: String,
        path: String,
        line: Int?,
        side: String = "RIGHT",
    ): Map<String, Any> {
        val token = tokenProvider.getInstallationToken(installationId)

        logger.debug { "Creating review comment on $owner/$repo#$prNumber at $path:$line" }

        val requestBody = mutableMapOf<String, Any>(
            "body" to body,
            "commit_id" to commitId,
            "path" to path,
            "side" to side,
        )
        if (line != null) {
            requestBody["line"] = line
        }

        return webClient.post()
            .uri("/repos/{owner}/{repo}/pulls/{prNumber}/comments", owner, repo, prNumber)
            .header("Authorization", "token $token")
            .header("Accept", "application/vnd.github+json")
            .contentType(MediaType.APPLICATION_JSON)
            .bodyValue(requestBody)
            .retrieve()
            .onStatus({ it.isError }) { clientResponse ->
                clientResponse.bodyToMono<String>().map { body2 ->
                    logger.error { "GitHub API error creating comment: ${clientResponse.statusCode()} - $body2" }
                    ApiException(
                        status = HttpStatus.valueOf(clientResponse.statusCode().value()),
                        message = "Failed to create review comment: $body2",
                        errorCode = "github_api_error",
                    )
                }
            }
            .bodyToMono<Map<String, Any>>()
            .awaitSingle()
    }
}
