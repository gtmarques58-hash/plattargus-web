<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class Autoridade extends Model
{
    protected $table = 'autoridades';
    
    protected $fillable = [
        'sigla',
        'nome',
        'posto_grad',
        'cargo',
        'unidade',
        'sigla_sei',
        'matricula',
        'portaria',
        'email',
        'telefone',
        'sigla_pai',
        'ativo',
    ];
    
    protected $casts = [
        'ativo' => 'boolean',
    ];
    
    /**
     * Retorna autoridades ativas ordenadas por sigla
     */
    public function scopeAtivas($query)
    {
        return $query->where('ativo', true)->orderBy('sigla');
    }
    
    /**
     * Busca por sigla ou nome
     */
    public function scopeBuscar($query, string $termo)
    {
        return $query->where(function ($q) use ($termo) {
            $q->where('sigla', 'ILIKE', "%{$termo}%")
              ->orWhere('nome', 'ILIKE', "%{$termo}%")
              ->orWhere('unidade', 'ILIKE', "%{$termo}%")
              ->orWhere('cargo', 'ILIKE', "%{$termo}%");
        });
    }
    
    /**
     * Retorna nome formatado: POSTO NOME - CARGO
     */
    public function getNomeCompletoAttribute(): string
    {
        $partes = [];
        if ($this->posto_grad) {
            $partes[] = $this->posto_grad;
        }
        $partes[] = $this->nome;
        
        $resultado = implode(' ', $partes);
        
        if ($this->cargo) {
            $resultado .= ' - ' . $this->cargo;
        }
        
        return $resultado;
    }
    
    /**
     * Retorna para dropdown: [SIGLA] POSTO NOME
     */
    public function getOpcaoDropdownAttribute(): string
    {
        return "[{$this->sigla}] {$this->posto_grad} {$this->nome}";
    }
}
