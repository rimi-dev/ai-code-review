package com.reviewer.domain.repository

import com.reviewer.domain.model.RegisteredRepository
import kotlinx.coroutines.flow.Flow
import org.springframework.data.repository.kotlin.CoroutineCrudRepository

interface RegisteredRepositoryRepository : CoroutineCrudRepository<RegisteredRepository, String> {
    suspend fun findByFullName(fullName: String): RegisteredRepository?
    fun findByEnabled(enabled: Boolean): Flow<RegisteredRepository>
    suspend fun findByOwner(owner: String): List<RegisteredRepository>
    suspend fun existsByFullName(fullName: String): Boolean
}
