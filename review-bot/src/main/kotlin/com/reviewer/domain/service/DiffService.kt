package com.reviewer.domain.service

import com.reviewer.config.properties.ReviewProperties
import org.springframework.stereotype.Service

@Service
class DiffService(
    private val reviewProperties: ReviewProperties,
) {
    data class FileDiff(
        val filePath: String,
        val hunks: List<DiffHunk>,
        val additions: Int = 0,
        val deletions: Int = 0,
    )

    data class DiffHunk(
        val header: String,
        val lines: List<DiffLine>,
        val newStartLine: Int,
    )

    data class DiffLine(
        val content: String,
        val type: LineType,
        val lineNumber: Int?,
    )

    enum class LineType { ADDED, REMOVED, CONTEXT }

    fun parseDiff(rawDiff: String): List<FileDiff> {
        val fileDiffs = mutableListOf<FileDiff>()
        val fileBlocks = rawDiff.split("diff --git ").filter { it.isNotBlank() }

        for (block in fileBlocks) {
            val lines = block.lines()
            val filePath = extractFilePath(lines) ?: continue

            if (shouldExclude(filePath)) continue

            val hunks = parseHunks(lines)
            val additions = hunks.sumOf { h -> h.lines.count { it.type == LineType.ADDED } }
            val deletions = hunks.sumOf { h -> h.lines.count { it.type == LineType.REMOVED } }

            fileDiffs.add(FileDiff(filePath, hunks, additions, deletions))
        }

        return fileDiffs.take(reviewProperties.maxFiles)
    }

    fun shouldExclude(filePath: String): Boolean {
        return reviewProperties.excludePatterns.any { pattern ->
            val regex = pattern
                .replace(".", "\\.")
                .replace("*", ".*")
                .toRegex()
            regex.containsMatchIn(filePath)
        }
    }

    fun buildDiffContext(fileDiff: FileDiff): String {
        return fileDiff.hunks.joinToString("\n") { hunk ->
            hunk.header + "\n" + hunk.lines.joinToString("\n") { line ->
                when (line.type) {
                    LineType.ADDED -> "+${line.content}"
                    LineType.REMOVED -> "-${line.content}"
                    LineType.CONTEXT -> " ${line.content}"
                }
            }
        }
    }

    private fun extractFilePath(lines: List<String>): String? {
        for (line in lines) {
            if (line.startsWith("+++ b/")) {
                return line.removePrefix("+++ b/")
            }
        }
        return null
    }

    private fun parseHunks(lines: List<String>): List<DiffHunk> {
        val hunks = mutableListOf<DiffHunk>()
        var currentHunkLines = mutableListOf<DiffLine>()
        var currentHeader = ""
        var currentNewLine = 0
        var lineNumber = 0

        for (line in lines) {
            if (line.startsWith("@@")) {
                if (currentHunkLines.isNotEmpty()) {
                    hunks.add(DiffHunk(currentHeader, currentHunkLines, currentNewLine))
                }
                currentHeader = line
                currentHunkLines = mutableListOf()
                currentNewLine = extractNewLineNumber(line)
                lineNumber = currentNewLine
                continue
            }

            if (currentHeader.isEmpty()) continue

            when {
                line.startsWith("+") && !line.startsWith("+++") -> {
                    currentHunkLines.add(DiffLine(line.removePrefix("+"), LineType.ADDED, lineNumber))
                    lineNumber++
                }
                line.startsWith("-") && !line.startsWith("---") -> {
                    currentHunkLines.add(DiffLine(line.removePrefix("-"), LineType.REMOVED, null))
                }
                else -> {
                    currentHunkLines.add(DiffLine(line.removePrefix(" "), LineType.CONTEXT, lineNumber))
                    lineNumber++
                }
            }
        }

        if (currentHunkLines.isNotEmpty()) {
            hunks.add(DiffHunk(currentHeader, currentHunkLines, currentNewLine))
        }

        return hunks
    }

    private fun extractNewLineNumber(hunkHeader: String): Int {
        val match = Regex("""@@ -\d+(?:,\d+)? \+(\d+)""").find(hunkHeader)
        return match?.groupValues?.get(1)?.toIntOrNull() ?: 1
    }
}
