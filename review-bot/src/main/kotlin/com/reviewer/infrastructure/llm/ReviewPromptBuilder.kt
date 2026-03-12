package com.reviewer.infrastructure.llm

import org.springframework.stereotype.Component

@Component
class ReviewPromptBuilder {

    fun buildSystemPrompt(language: String = "en", customPrompt: String? = null): String {
        val basePrompt = """
            You are an expert code reviewer. Analyze the provided code diff and generate constructive review comments.

            Response format: Return a JSON array of review comments. Each comment must have:
            - "file": file path
            - "line": line number in the diff (positive integer)
            - "severity": one of "CRITICAL", "WARNING", "SUGGESTION", "PRAISE"
            - "category": one of "bug", "security", "performance", "quality", "best-practice", "style"
            - "title": short summary (1 line)
            - "body": detailed explanation
            - "suggestion": optional code suggestion

            Guidelines:
            - Focus on meaningful issues (bugs, security, performance)
            - Be specific with line references
            - Provide actionable suggestions
            - Use ${if (language == "ko") "Korean" else "English"} for review comments
            - Return ONLY the JSON array, no markdown wrapping
        """.trimIndent()

        return if (customPrompt != null) {
            "$basePrompt\n\nAdditional rules:\n$customPrompt"
        } else {
            basePrompt
        }
    }

    fun buildUserPrompt(
        prTitle: String,
        prBody: String?,
        files: List<String>,
        diffContent: String,
    ): String {
        return buildString {
            appendLine("## Pull Request")
            appendLine("Title: $prTitle")
            if (!prBody.isNullOrBlank()) {
                appendLine("Description: ${prBody.take(500)}")
            }
            appendLine()
            appendLine("## Changed Files")
            files.forEach { appendLine("- $it") }
            appendLine()
            appendLine("## Diff")
            appendLine("```diff")
            appendLine(diffContent)
            appendLine("```")
        }
    }

    fun buildChunkedUserPrompt(
        prTitle: String,
        prBody: String?,
        file: String,
        patch: String,
        chunkIndex: Int,
        totalChunks: Int,
    ): String {
        return buildString {
            appendLine("## Pull Request")
            appendLine("Title: $prTitle")
            if (!prBody.isNullOrBlank()) {
                appendLine("Description: ${prBody.take(300)}")
            }
            appendLine()
            appendLine("## File ($chunkIndex/$totalChunks): $file")
            appendLine()
            appendLine("```diff")
            appendLine(patch)
            appendLine("```")
        }
    }
}
