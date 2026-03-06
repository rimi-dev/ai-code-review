package com.reviewer.api.webhook

import com.reviewer.infrastructure.git.dto.WebhookPayload
import io.github.oshai.kotlinlogging.KotlinLogging
import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestHeader
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

private val logger = KotlinLogging.logger {}

@RestController
@RequestMapping("/api/v1/webhook")
class WebhookController(
    private val webhookService: WebhookService,
) {

    @PostMapping("/github")
    suspend fun handleGitHubWebhook(
        @RequestHeader("X-GitHub-Event") eventType: String,
        @RequestHeader("X-Hub-Signature-256", required = false) signature: String?,
        @RequestHeader("X-GitHub-Delivery", required = false) deliveryId: String?,
        @RequestBody payload: ByteArray,
    ): ResponseEntity<Map<String, String>> {
        logger.info { "Received GitHub webhook: event=$eventType, delivery=$deliveryId" }

        // Parse payload for structured processing
        val objectMapper = tools.jackson.databind.json.JsonMapper.builder()
            .findAndAddModules()
            .disable(tools.jackson.databind.DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
            .build()

        val parsedPayload = objectMapper.readValue(payload, WebhookPayload::class.java)

        webhookService.handleWebhook(
            eventType = eventType,
            signature = signature,
            payload = payload,
            parsedPayload = parsedPayload,
        )

        return ResponseEntity.ok(mapOf("status" to "accepted"))
    }
}
