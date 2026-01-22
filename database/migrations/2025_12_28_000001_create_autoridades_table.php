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
        Schema::create('autoridades', function (Blueprint $table) {
            $table->id();
            $table->string('sigla', 50)->unique();  // CMDGER, DRH, COI, etc.
            $table->string('nome', 255);            // Nome completo da pessoa
            $table->string('posto_grad', 50)->nullable();  // CEL QOBMEC, MAJ QOBMEC, etc.
            $table->string('cargo', 255)->nullable();      // Comandante-Geral, Diretor, etc.
            $table->string('unidade', 255);         // Nome completo da unidade
            $table->string('sigla_sei', 50)->nullable();   // CBMAC-CMDGER, CBMAC-DRH
            $table->string('matricula', 50)->nullable();
            $table->string('portaria', 255)->nullable();   // Decreto/Portaria de nomeação
            $table->string('email', 255)->nullable();
            $table->string('telefone', 50)->nullable();
            $table->string('sigla_pai', 50)->nullable();   // Hierarquia (pai)
            $table->boolean('ativo')->default(true);
            $table->timestamps();
            
            $table->index('sigla');
            $table->index('ativo');
        });
    }

    /**
     * Reverse the migrations.
     */
    public function down(): void
    {
        Schema::dropIfExists('autoridades');
    }
};
