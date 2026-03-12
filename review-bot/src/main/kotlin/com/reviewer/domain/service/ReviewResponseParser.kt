package com.reviewer.domain.service

import com.reviewer.domain.model.ReviewCommentEmbed
import io.github.oshai.kotlinlogging.KotlinLogging
import org.springframework.stereotype.Service
import tools.jackson.databind.DeserializationFeature
import tools.jackson.databind.PropertyNamingStrategies
import tools.jackson.databind.json.JsonMapper
import tools.jackson.module.kotlin.readValue

private val logger = KotlinLogging.logger {}

@Service
class ReviewResponseParser {

    private val objectMapper = JsonMapper.builder()
        .findAndAddModules()
        .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)
        .propertyNamingStrategy(PropertyNamingStrategies.SNAKE_CASE)
        .build()

    data class ParsedComment(
        val file: String = "",
        val line: Int = 0,
        val severity: String = "SUGGESTION",
        val category: String = "quality",
        val title: String = "",
        val body: String = "",
        val suggestion: String? = null,
    )

    fun parse(llmResponse: String): List<ReviewCommentEmbed> {
        return try {
            val jsonContent = extractJson(llmResponse)
            val parsed: List<ParsedComment> = objectMapper.readValue(jsonContent)
            parsed.map { comment ->
                ReviewCommentEmbed(
                    filePath = comment.file,
                    lineNumber = comment.line,
                    category = comment.category.lowercase(),
                    severity = normalizeSeverity(comment.severity),
                    content = "${comment.title}\n\n${comment.body}",
                    suggestion = comment.suggestion,
                )
            }
        } catch (e: Exception) {
            logger.warn(e) { "Failed to parse LLM response as JSON" }
            emptyList()
        }
    }

    private fun extractJson(response: String): String {
        val codeBlockMatch = Regex("```(?:json)?\\s*\\n?(\\[.*?])\\s*```", RegexOption.DOT_MATCHES_ALL)
            .find(response)
        if (codeBlockMatch != null) return codeBlockMatch.groupValues[1]

        val arrayMatch = Regex("\\[.*]", RegexOption.DOT_MATCHES_ALL).find(response)
        if (arrayMatch != null) return arrayMatch.value

        return response
    }

    private fun normalizeSeverity(severity: String): String {
        return when (severity.uppercase()) {
            "CRITICAL" -> "CRITICAL"
            "WARNING" -> "WARNING"
            "SUGGESTION" -> "SUGGESTION"
            "PRAISE" -> "PRAISE"
            "INFO" -> "SUGGESTION"
            else -> "SUGGESTION"
        }
    }
}
