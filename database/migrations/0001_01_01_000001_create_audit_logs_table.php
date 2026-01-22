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
        Schema::create('audit_logs', function (Blueprint $table) {
            $table->id();
            
            // =========================================================
            // CONTEXTO
            // =========================================================
            $table->foreignId('user_id')
                  ->nullable()
                  ->constrained()
                  ->nullOnDelete();
            
            // =========================================================
            // AÇÃO
            // =========================================================
            $table->string('action', 50);           // login, sign, step_up, etc.
            $table->string('target_type', 50)->nullable();  // document, process, etc.
            $table->string('target_id', 100)->nullable();   // NUP, SEI número, etc.
            
            // =========================================================
            // RESULTADO
            // =========================================================
            $table->string('status', 20);           // success, failure, denied
            
            // =========================================================
            // METADADOS
            // =========================================================
            $table->ipAddress('ip_address')->nullable();
            $table->text('user_agent')->nullable();
            $table->jsonb('metadata')->nullable();  // Dados extras
            
            // =========================================================
            // TIMESTAMP (imutável, sem updated_at)
            // =========================================================
            $table->timestamp('created_at')->useCurrent();
            
            // =========================================================
            // ÍNDICES PARA CONSULTAS FREQUENTES
            // =========================================================
            $table->index('action');
            $table->index('status');
            $table->index('created_at');
            $table->index(['user_id', 'created_at']);
            $table->index(['action', 'created_at']);
            $table->index(['target_type', 'target_id']);
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('audit_logs');
    }
};
