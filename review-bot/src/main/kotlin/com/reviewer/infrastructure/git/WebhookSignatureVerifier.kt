package com.reviewer.infrastructure.git

import org.springframework.stereotype.Component
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

@Component
class WebhookSignatureVerifier {

    fun verify(payload: ByteArray, signature: String, secret: String): Boolean {
        if (secret.isBlank()) return true
        if (!signature.startsWith("sha256=")) return false

        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(secret.toByteArray(), "HmacSHA256"))
        val expected = "sha256=" + mac.doFinal(payload).joinToString("") { "%02x".format(it) }

        return expected.equals(signature, ignoreCase = true)
    }
}
