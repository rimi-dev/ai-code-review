package com.reviewer.api.webhook

import org.springframework.http.ResponseEntity
import org.springframework.web.bind.annotation.PostMapping
import org.springframework.web.bind.annotation.RequestBody
import org.springframework.web.bind.annotation.RequestHeader
import org.springframework.web.bind.annotation.RequestMapping
import org.springframework.web.bind.annotation.RestController

@RestController
@RequestMapping("/api/v1/webhooks")
class WebhookController(
    private val webhookService: WebhookService,
) {
    @PostMapping("/github")
    suspend fun handleGitHubWebhook(
        @RequestHeader("X-GitHub-Event") event: String,
        @RequestHeader("X-Hub-Signature-256") signature: String,
        @RequestBody body: ByteArray,
    ): ResponseEntity<Map<String, String>> {
        webhookService.handleWebhook(event, signature, body)
        return ResponseEntity.ok(mapOf("status" to "accepted"))
    }
}
