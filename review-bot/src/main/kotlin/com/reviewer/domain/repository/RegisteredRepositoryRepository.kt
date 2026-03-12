package com.reviewer.domain.repository

import com.reviewer.domain.model.RegisteredRepository
import org.springframework.data.repository.kotlin.CoroutineCrudRepository

interface RegisteredRepositoryRepository : CoroutineCrudRepository<RegisteredRepository, String> {
    suspend fun findByFullName(fullName: String): RegisteredRepository?
    suspend fun findByIsActive(isActive: Boolean): List<RegisteredRepository>
}
