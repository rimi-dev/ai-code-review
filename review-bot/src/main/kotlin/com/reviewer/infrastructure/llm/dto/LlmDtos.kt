package com.reviewer.infrastructure.llm.dto

// === Common Response ===
data class ReviewLlmResponse(
    val content: String,
    val model: String,
    val provider: String,
    val inputTokens: Int = 0,
    val outputTokens: Int = 0,
    val totalTokens: Int = 0,
)

// === OpenAI Compatible ===
data class ChatCompletionRequest(
    val model: String,
    val messages: List<ChatMessage>,
    val temperature: Double = 0.1,
    val maxTokens: Int = 4096,
    val stream: Boolean = false,
)

data class ChatMessage(
    val role: String,
    val content: String,
)

data class ChatCompletionResponse(
    val id: String,
    val model: String,
    val choices: List<ChatChoice> = emptyList(),
    val usage: OpenAiUsage? = null,
)

data class ChatChoice(
    val index: Int = 0,
    val message: ChatMessage,
    val finishReason: String? = null,
)

data class OpenAiUsage(
    val promptTokens: Int = 0,
    val completionTokens: Int = 0,
    val totalTokens: Int = 0,
)

// === Claude (Anthropic Messages API) ===
data class ClaudeMessagesRequest(
    val model: String,
    val maxTokens: Int,
    val system: String? = null,
    val messages: List<ClaudeMessage>,
    val temperature: Double? = null,
    val stream: Boolean = false,
)

data class ClaudeMessage(
    val role: String,
    val content: String,
)

data class ClaudeMessagesResponse(
    val id: String,
    val type: String,
    val role: String,
    val content: List<ClaudeContent>,
    val model: String,
    val stopReason: String?,
    val usage: ClaudeUsage,
)

data class ClaudeContent(
    val type: String,
    val text: String? = null,
)

data class ClaudeUsage(
    val inputTokens: Int,
    val outputTokens: Int,
)

// === Gemini ===
data class GeminiGenerateRequest(
    val contents: List<GeminiContent>,
    val systemInstruction: GeminiContent? = null,
    val generationConfig: GeminiGenerationConfig? = null,
)

data class GeminiContent(
    val role: String? = null,
    val parts: List<GeminiPart>,
)

data class GeminiPart(
    val text: String,
)

data class GeminiGenerationConfig(
    val temperature: Double? = null,
    val maxOutputTokens: Int? = null,
)

data class GeminiGenerateResponse(
    val candidates: List<GeminiCandidate> = emptyList(),
    val usageMetadata: GeminiUsageMetadata? = null,
)

data class GeminiCandidate(
    val content: GeminiContent,
    val finishReason: String? = null,
)

data class GeminiUsageMetadata(
    val promptTokenCount: Int = 0,
    val candidatesTokenCount: Int = 0,
    val totalTokenCount: Int = 0,
)
