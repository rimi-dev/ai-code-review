package com.reviewer.domain.service

import com.reviewer.domain.model.ReviewComment
import com.reviewer.domain.model.Severity
import io.github.oshai.kotlinlogging.KotlinLogging
import org.springframework.stereotype.Component
import tools.jackson.databind.ObjectMapper

private val logger = KotlinLogging.logger {}

@Component
class ReviewResponseParser(
    private val objectMapper: ObjectMapper,
) {

    data class ParsedComment(
        val file: String,
        val line: Int?,
        val severity: String,
        val category: String,
        val title: String,
        val body: String,
        val suggestion: String? = null,
    )

    fun parse(
        llmResponse: String,
        reviewRequestId: String,
        repositoryFullName: String,
        pullRequestNumber: Int,
    ): List<ReviewComment> {
        val jsonContent = extractJsonArray(llmResponse)
        if (jsonContent.isNullOrBlank()) {
            logger.warn { "No JSON array found in LLM response for reviewRequestId=$reviewRequestId" }
            return emptyList()
        }

        return try {
            val typeRef = objectMapper.typeFactory.constructCollectionType(
                List::class.java,
                ParsedComment::class.java,
            )
            val parsedComments: List<ParsedComment> = objectMapper.readValue(jsonContent, typeRef)

            parsedComments.mapNotNull { parsed ->
                try {
                    ReviewComment(
                        reviewRequestId = reviewRequestId,
                        repositoryFullName = repositoryFullName,
                        pullRequestNumber = pullRequestNumber,
                        filePath = parsed.file,
                        line = parsed.line,
                        severity = parseSeverity(parsed.severity),
                        category = parsed.category,
                        title = parsed.title,
                        body = parsed.body,
                        suggestion = parsed.suggestion,
                    )
                } catch (e: Exception) {
                    logger.warn(e) { "Failed to map parsed comment: ${parsed.title}" }
                    null
                }
            }
        } catch (e: Exception) {
            logger.error(e) { "Failed to parse LLM response JSON for reviewRequestId=$reviewRequestId" }
            emptyList()
        }
    }

    private fun extractJsonArray(response: String): String? {
        // Try to find JSON array within markdown code blocks
        val codeBlockPattern = Regex("```(?:json)?\\s*\\n?(\\[.*?])\\s*\\n?```", RegexOption.DOT_MATCHES_ALL)
        val codeBlockMatch = codeBlockPattern.find(response)
        if (codeBlockMatch != null) {
            return codeBlockMatch.groupValues[1].trim()
        }

        // Try to find a bare JSON array
        val arrayPattern = Regex("(\\[\\s*\\{.*}\\s*])", RegexOption.DOT_MATCHES_ALL)
        val arrayMatch = arrayPattern.find(response)
        if (arrayMatch != null) {
            return arrayMatch.groupValues[1].trim()
        }

        // Check for empty array
        if (response.contains("[]")) {
            return "[]"
        }

        return null
    }

    private fun parseSeverity(value: String): Severity {
        return try {
            Severity.valueOf(value.uppercase())
        } catch (e: IllegalArgumentException) {
            logger.warn { "Unknown severity: $value, defaulting to SUGGESTION" }
            Severity.SUGGESTION
        }
    }
}
