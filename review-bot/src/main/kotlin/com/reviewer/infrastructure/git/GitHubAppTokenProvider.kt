package com.reviewer.infrastructure.git

import com.reviewer.api.exception.ApiException
import com.reviewer.config.properties.GitHubProperties
import com.reviewer.infrastructure.git.dto.InstallationTokenResponse
import io.github.oshai.kotlinlogging.KotlinLogging
import kotlinx.coroutines.reactor.awaitSingle
import org.springframework.http.HttpStatus
import org.springframework.http.MediaType
import org.springframework.stereotype.Component
import org.springframework.web.reactive.function.client.WebClient
import org.springframework.web.reactive.function.client.bodyToMono
import java.nio.file.Files
import java.nio.file.Path
import java.security.KeyFactory
import java.security.spec.PKCS8EncodedKeySpec
import java.time.Instant
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap

private val logger = KotlinLogging.logger {}

@Component
class GitHubAppTokenProvider(
    webClientBuilder: WebClient.Builder,
    private val gitHubProperties: GitHubProperties,
) {

    private val webClient: WebClient = webClientBuilder
        .baseUrl(gitHubProperties.apiBaseUrl)
        .build()

    private val tokenCache = ConcurrentHashMap<Long, CachedToken>()

    data class CachedToken(
        val token: String,
        val expiresAt: Instant,
    )

    suspend fun getInstallationToken(installationId: Long): String {
        val cached = tokenCache[installationId]
        if (cached != null && cached.expiresAt.isAfter(Instant.now().plusSeconds(60))) {
            return cached.token
        }

        logger.debug { "Fetching new installation token for installationId=$installationId" }

        val jwt = generateJwt()

        val response = webClient.post()
            .uri("/app/installations/{installationId}/access_tokens", installationId)
            .header("Authorization", "Bearer $jwt")
            .header("Accept", "application/vnd.github+json")
            .contentType(MediaType.APPLICATION_JSON)
            .retrieve()
            .onStatus({ it.isError }) { clientResponse ->
                clientResponse.bodyToMono<String>().map { body ->
                    logger.error { "GitHub token exchange error: ${clientResponse.statusCode()} - $body" }
                    ApiException(
                        status = HttpStatus.valueOf(clientResponse.statusCode().value()),
                        message = "Failed to get installation token: $body",
                        errorCode = "github_token_error",
                    )
                }
            }
            .bodyToMono<InstallationTokenResponse>()
            .awaitSingle()

        val expiresAt = response.expiresAt ?: Instant.now().plusSeconds(3500)
        tokenCache[installationId] = CachedToken(response.token, expiresAt)

        logger.info { "Obtained installation token for installationId=$installationId, expiresAt=$expiresAt" }

        return response.token
    }

    private fun generateJwt(): String {
        val now = Instant.now()
        val issuedAt = now.minusSeconds(60)
        val expiration = now.plusSeconds(600)

        val header = Base64.getUrlEncoder().withoutPadding()
            .encodeToString("""{"alg":"RS256","typ":"JWT"}""".toByteArray())

        val payload = Base64.getUrlEncoder().withoutPadding()
            .encodeToString(
                """{
                    "iat":${issuedAt.epochSecond},
                    "exp":${expiration.epochSecond},
                    "iss":"${gitHubProperties.appId}"
                }""".trimIndent().toByteArray(),
            )

        val signingInput = "$header.$payload"
        val privateKey = loadPrivateKey()

        val signature = java.security.Signature.getInstance("SHA256withRSA").apply {
            initSign(privateKey)
            update(signingInput.toByteArray())
        }

        val signatureBytes = signature.sign()
        val encodedSignature = Base64.getUrlEncoder().withoutPadding()
            .encodeToString(signatureBytes)

        return "$header.$payload.$encodedSignature"
    }

    private fun loadPrivateKey(): java.security.PrivateKey {
        val keyContent = Files.readString(Path.of(gitHubProperties.privateKeyPath))
            .replace("-----BEGIN RSA PRIVATE KEY-----", "")
            .replace("-----END RSA PRIVATE KEY-----", "")
            .replace("-----BEGIN PRIVATE KEY-----", "")
            .replace("-----END PRIVATE KEY-----", "")
            .replace("\\s".toRegex(), "")

        val keyBytes = Base64.getDecoder().decode(keyContent)
        val keySpec = PKCS8EncodedKeySpec(keyBytes)
        val keyFactory = KeyFactory.getInstance("RSA")
        return keyFactory.generatePrivate(keySpec)
    }
}
