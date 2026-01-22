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
        Schema::create('templates_documento', function (Blueprint $table) {
            $table->id();
            $table->string('codigo', 50)->unique();      // MEMO_GENERICO, DESPACHO_SIMPLES, etc.
            $table->string('tipo_sei', 100);             // Memorando, Despacho, Ofício, etc.
            $table->string('categoria', 50);             // memorandos, despachos, oficios, etc.
            $table->string('nome', 255);                 // Nome amigável
            $table->text('descricao')->nullable();       // Descrição do uso
            $table->text('conteudo_html');               // Template HTML com placeholders
            $table->json('campos')->nullable();          // Lista de campos obrigatórios
            $table->string('remetente_tipo', 50)->default('chefe_unidade'); // chefe_unidade, usuario_logado
            $table->boolean('ativo')->default(true);
            $table->integer('ordem')->default(0);        // Ordem de exibição
            $table->timestamps();
            
            $table->index('tipo_sei');
            $table->index('categoria');
            $table->index('ativo');
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('templates_documento');
    }
};
