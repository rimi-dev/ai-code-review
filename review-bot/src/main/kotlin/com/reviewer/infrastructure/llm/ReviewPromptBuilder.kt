package com.reviewer.infrastructure.llm

import com.reviewer.domain.model.ReviewConfig
import com.reviewer.infrastructure.git.dto.PrFile
import org.springframework.stereotype.Component

@Component
class ReviewPromptBuilder {

    fun buildSystemPrompt(language: String, customPrompt: String?): String {
        val basePrompt = """
            |You are an expert code reviewer. Review the provided code diff and provide actionable feedback.
            |
            |Your review should focus on:
            |1. **Bugs & Errors**: Logic errors, potential runtime exceptions, null pointer issues
            |2. **Security**: SQL injection, XSS, authentication/authorization issues, secrets exposure
            |3. **Performance**: N+1 queries, unnecessary allocations, missing indexes
            |4. **Code Quality**: Naming, readability, DRY violations, design patterns
            |5. **Best Practices**: Error handling, logging, testing considerations
            |
            |Response format - return a JSON array of review comments:
            |```json
            |[
            |  {
            |    "file": "path/to/file.kt",
            |    "line": 42,
            |    "severity": "CRITICAL|WARNING|SUGGESTION|PRAISE",
            |    "category": "bug|security|performance|quality|best-practice",
            |    "title": "Short descriptive title",
            |    "body": "Detailed explanation of the issue and why it matters",
            |    "suggestion": "Optional: suggested code fix"
            |  }
            |]
            |```
            |
            |Rules:
            |- Only comment on changed lines (lines with + prefix in the diff)
            |- Be concise but thorough
            |- Provide specific line numbers from the diff
            |- Use CRITICAL only for bugs that will cause failures or security vulnerabilities
            |- Use PRAISE sparingly for genuinely excellent patterns
            |- If no issues found, return an empty array: []
            |- Response language: $language
        """.trimMargin()

        return if (customPrompt != null) {
            "$basePrompt\n\nAdditional instructions:\n$customPrompt"
        } else {
            basePrompt
        }
    }

    fun buildUserPrompt(
        prTitle: String,
        prBody: String?,
        files: List<PrFile>,
        diffContent: String,
    ): String {
        val fileList = files.joinToString("\n") { file ->
            "- ${file.filename} (${file.status}: +${file.additions}/-${file.deletions})"
        }

        return """
            |## Pull Request
            |**Title**: $prTitle
            |${if (!prBody.isNullOrBlank()) "**Description**: $prBody" else ""}
            |
            |## Changed Files
            |$fileList
            |
            |## Diff
            |```diff
            |$diffContent
            |```
        """.trimMargin()
    }

    fun buildChunkedUserPrompt(
        prTitle: String,
        prBody: String?,
        file: PrFile,
        patch: String,
        chunkIndex: Int,
        totalChunks: Int,
    ): String {
        return """
            |## Pull Request
            |**Title**: $prTitle
            |${if (!prBody.isNullOrBlank()) "**Description**: $prBody" else ""}
            |
            |## File (${chunkIndex + 1}/$totalChunks)
            |**Path**: ${file.filename}
            |**Status**: ${file.status} (+${file.additions}/-${file.deletions})
            |
            |## Diff
            |```diff
            |$patch
            |```
        """.trimMargin()
    }
}
