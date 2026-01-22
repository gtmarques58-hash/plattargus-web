<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    /**
     * Run the migrations.
     */
    public function up(): void
    {
        // =========================================================
        // JOBS DO SEI (controle de execução assíncrona)
        // =========================================================
        Schema::create('sei_jobs', function (Blueprint $table) {
            $table->string('id', 50)->primary();  // job_01JH...
            
            $table->foreignId('user_id')
                  ->constrained()
                  ->cascadeOnDelete();
            
            // Tipo de job
            $table->string('type', 30);           // analyze, sign, generate, insert
            
            // Status
            $table->string('status', 20)          // queued, running, done, error, canceled
                  ->default('queued');
            
            // Dados do processo
            $table->string('nup', 50)->nullable();
            $table->string('sei_numero', 20)->nullable();
            
            // Payload da requisição
            $table->jsonb('request_data')->nullable();
            
            // Resultado
            $table->jsonb('result_data')->nullable();
            $table->text('error_message')->nullable();
            
            // Progresso
            $table->unsignedTinyInteger('progress_pct')->default(0);
            $table->string('progress_step', 50)->nullable();
            
            // Timestamps
            $table->timestamps();
            $table->timestamp('started_at')->nullable();
            $table->timestamp('finished_at')->nullable();
            
            // Índices
            $table->index('status');
            $table->index(['user_id', 'status']);
            $table->index(['user_id', 'created_at']);
            $table->index('nup');
        });

        // =========================================================
        // ANÁLISES DE PROCESSO (resultados salvos)
        // =========================================================
        Schema::create('process_analyses', function (Blueprint $table) {
            $table->id();
            
            $table->string('job_id', 50)->nullable();
            
            $table->foreignId('user_id')
                  ->constrained()
                  ->cascadeOnDelete();
            
            // Dados do processo
            $table->string('nup', 50)->index();
            
            // Análise estruturada
            $table->text('resumo')->nullable();
            $table->text('conclusao')->nullable();
            
            // Dados extraídos (JSON)
            $table->jsonb('interessado')->nullable();
            $table->jsonb('pedido')->nullable();
            $table->jsonb('legislacao')->nullable();
            $table->jsonb('documentos')->nullable();
            $table->jsonb('alertas')->nullable();
            $table->jsonb('unidades')->nullable();
            
            // Texto bruto (para chat analítico)
            $table->text('texto_canonico')->nullable();
            
            // Timestamps
            $table->timestamps();
            
            // Índices
            $table->index(['user_id', 'created_at']);
            $table->index('job_id');
        });

        // =========================================================
        // DOCUMENTOS GERADOS
        // =========================================================
        Schema::create('generated_documents', function (Blueprint $table) {
            $table->id();
            
            $table->foreignId('user_id')
                  ->constrained()
                  ->cascadeOnDelete();
            
            $table->foreignId('process_analysis_id')
                  ->nullable()
                  ->constrained()
                  ->nullOnDelete();
            
            // Dados do documento
            $table->string('nup', 50)->index();
            $table->string('tipo', 50);           // despacho, memorando, etc.
            $table->string('destinatario', 100)->nullable();
            
            // Conteúdo
            $table->text('conteudo_html');
            $table->text('conteudo_texto')->nullable();
            
            // Status no SEI
            $table->string('sei_numero', 20)->nullable();  // Se foi inserido
            $table->boolean('inserido_sei')->default(false);
            $table->boolean('assinado')->default(false);
            $table->timestamp('inserido_em')->nullable();
            $table->timestamp('assinado_em')->nullable();
            
            // Timestamps
            $table->timestamps();
            
            // Índices
            $table->index(['user_id', 'created_at']);
            $table->index('sei_numero');
        });

        // =========================================================
        // CACHE DE SESSÕES SEI (storage_state do Playwright)
        // =========================================================
        Schema::create('sei_sessions', function (Blueprint $table) {
            $table->id();
            
            $table->foreignId('user_id')
                  ->unique()  // 1 sessão por usuário
                  ->constrained()
                  ->cascadeOnDelete();
            
            // Storage state do Playwright (cookies, localStorage)
            $table->text('storage_state')->nullable();
            
            // Validade
            $table->timestamp('expires_at');
            $table->boolean('is_valid')->default(true);
            
            // Metadados
            $table->unsignedTinyInteger('shard_id')->nullable();
            $table->timestamp('last_verified_at')->nullable();
            
            // Timestamps
            $table->timestamps();
            
            // Índices
            $table->index('expires_at');
            $table->index('is_valid');
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('sei_sessions');
        Schema::dropIfExists('generated_documents');
        Schema::dropIfExists('process_analyses');
        Schema::dropIfExists('sei_jobs');
    }
};
