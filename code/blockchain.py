"""
Blockchain (stub).
"""
import time
import datetime
import json
import random
import argparse
import sys
import operator
import threading
import copy 
from hashlib import sha256
from flask import Flask, request
from requests import get, post, exceptions
from broadcast import Broadcast, send_to_one


class TransactionEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Transaction):
            return vars(obj)
        return json.JSONEncoder.default(self, obj)



class Block:
    def __init__(self, index, transactions, timestamp, previous_hash, nonce = 0):
        """Init the properties of a block.
        """
        self._index = index
        self._transactions = transactions
        self._timestamp = timestamp
        self._previous_hash = previous_hash
        self._nonce = nonce

    def proof(self, difficulty):
        """Returns the proof of the current block.
        """
        # print("Hash in proof",self.compute_hash())
        return self.compute_hash().startswith('0' * difficulty)
                
    def get_transactions(self):
        """Returns the list of transactions associated with the block.
        """
        return self._transactions

    def compute_hash(self):
        """
        Returns the hash of the block contents.
        """
        block_string = json.dumps(self.__dict__, sort_keys=True, cls=TransactionEncoder)
        return sha256(block_string.encode()).hexdigest()

    def _change_nonce(self, random = False):
        """
        Changes the nonce of a block.
        """
        if(random):
            self._nonce = random.randint(1, sys.maxsize)
        else:
            self._nonce += 1

    

class Transaction:
    def __init__(self, key, value, origin):
        """Init the transaction. A transaction typically involves
        some key, value and an origin (the one who put it onto the storage).
        """
        self.key = key
        self.value = value 
        self.origin = origin

    def __eq__(self, other):
        """
        Overwrite of the equality test.
        """
        return self.__dict__ == other.__dict__




class Blockchain:
    def __init__(self, port = 5000, miner = True, unitTests = False):
        """Init the blockchain.
        """
        # Initialize the properties.
        self._master_chain = []
        self._branch_list = []
        self._last_hash = None
        self._pending_transactions = []
        self._difficulty = 4
        self._miner = miner

        #Block confirmation request
        self._blocks_to_confirm = []
        self._block_to_mine = None
        
        self._confirm_block = False #Incoming Block confirmation flag
        self._block_added = False #Incoming block added flag

        #ip = get('https://api.ipify.org').text
        ip = "127.0.0.1"
        self._ip = "{}:{}".format(ip,port)
        

        if unitTests :
            self._add_genesis_block()
       
        self.broadcast = Broadcast(set(), self._ip)

        #Creating mining thread
        if self._miner:
            print("Create mining thread")
            mining_thread = threading.Thread(target = self.mine,daemon=True)
            mining_thread.start()

    def _add_genesis_block(self):
        """Adds the genesis block to your blockchain.
        """
        self._master_chain.append(Block(0, [], time.time(), "0"))
        self._last_hash = self._master_chain[-1].compute_hash()
        print("Genesis block added, hash :",self._last_hash)
    
    def bootstrap(self, address):
        """The bootstrap address serves as the initial entry point of
        the bootstrapping procedure. It will contact the specified
        address, download the peerlist, and start the bootstrapping procedure.
        """
        print("BOOSTRAPING -------------")
        if(address == self._get_ip()):
            # Initialize the chain with the Genesis block.
            self._add_genesis_block()
            return
        # Get the list of peer from bootstrap node
        try:
            result = send_to_one(address, "peers")
        except exceptions.RequestException:
            print("Unable to bootstrap (connection failed to bootstrap node)")
            return
        peers = result.json()["peers"]
        for peer in peers:
            self.add_node(peer)
        self.add_node(address)
        if(self._get_ip() in peers):
            peers.remove(self._get_ip())

        # Get all the blocks from a non-corrupted node
        hashes = {}
        for peer in self.get_peers():
            hashes[peer] = send_to_one(peer, "addNode", {"address" : self._get_ip()})
        if hashes:
            address = get_address_best_hash(hashes)
        result = send_to_one(address, "blockchain")
        chain = result.json()["chain"]

        # Reconstruct the chain
        init_chain = []
        for block in chain:
            block = json.loads(block)
            transaction = []

            for t in block["_transactions"]:
                transaction.append(Transaction(t["key"], t["value"], t["origin"]))
            
            new_block = Block(block["_index"], 
                                transaction, 
                                block["_timestamp"], 
                                block["_previous_hash"],
                                block["_nonce"])
            
            print("Bootstrap BLOCK:",new_block.compute_hash())
            init_chain.append(new_block)
        
        self._master_chain = init_chain
        self._last_hash = init_chain[-1].compute_hash()

        print("Bootstrap complete. Blockchain is now {} blocks long".format(len(self._master_chain)))
        # [print(block.__dict__) for block in self._master_chain]
        return
   
    def add_node(self, peer):
        """
        Add a node to the network.
        """
        self.broadcast.add_peer(peer)   

    def _get_ip(self):
        """
        Get ip address of a node.
        """
        return self._ip

    def _add_block(self,new_block):
        """
        Add a block to the blockchain if it is valid
        Apply longest chain rule
        Constraint: Discard block if the parent is more than 1 generation away
        from the master chain
        """

        #Check block validity
        if not new_block.proof(self._difficulty):
            print("Block has incorrect proof")
            return False

        new_block_hash = new_block.compute_hash()

        #Direct successors of last block from master node
        #Discard block if the parent is more than 1 generation away
        if new_block._previous_hash == self._master_chain[-1].compute_hash():
            self._branch_list.append([new_block])
            print("Block ID {} hash {} added to BRANCH".format(new_block._index, 
                            new_block_hash))
            return True

        createBranch = False
        for branch in self._branch_list:
            if createBranch:
                break
            #If parent of new_block is last block of the branch,
            #add it to the branch
            if branch[-1].compute_hash() == new_block._previous_hash:
                branch.append(new_block)
                createBranch = True
                print("Block ID {} hash {} added to BRANCH".format(new_block._index, 
                                new_block_hash))
                break
            #Else, copy the branch and add the new block to the copy
            for k, block in enumerate(branch):
                if new_block._previous_hash == block.compute_hash():
                    new_branch = copy.deepcopy(branch[:k+1])
                    new_branch.append(new_block)
                    self._branch_list.append(new_branch)
                    print("Block ID {} hash {} added to NEW BRANCH".format(new_block._index, 
                                new_block_hash))
                    createBranch = True
                    break

        max_len_branch = sorted(self._branch_list, key=len)[-1]
        max_len = len(sorted(self._branch_list, key=len)[-1])
        
        #Longest chain rule : part of branch longer or equal to 2 blocks get added
        if max_len >= 2:
            #Add all but one element to the master chain

            self._last_hash = max_len_branch[-1].compute_hash()
            self._master_chain.extend(max_len_branch[:-1])
            #Remove all  but one element from the list of branches
            self._branch_list = [[max_len_branch[-1]]]
            for block in max_len_branch[:-1]:
                print("Block ID {} hash {} added to MASTER".format(block._index, 
                        block.compute_hash()))

            return True
        
        return createBranch
    
    def _proof_of_work(self):
        """
        Implement the proof of work algorithm
        Also check for block confirmation request from another Node
        """
        #Reset nonce
        self._block_to_mine._nonce = 0

        #Get the real hash of the block
        computed_hash = self._block_to_mine.compute_hash()

        #Find the nonce that computes the right block hash
        while not computed_hash.startswith('0' * self._difficulty):
            
            if not self._confirm_block:
                self._block_to_mine._change_nonce()
                computed_hash = self._block_to_mine.compute_hash()
            
            if self._block_added:
                self._block_added = False
                #Discard currently mined block
                return False

        #Broadcast block to other nodes
        self.broadcast.broadcast("block",json.dumps(self._block_to_mine.__dict__,
                                                        sort_keys=True,
                                                        cls=TransactionEncoder))
        print("Mined block hash",computed_hash)
        self._last_hash = computed_hash
        return True

    def get_blocks(self):
        """ Returns all blocks from the chain.
        """
        return self._master_chain

    def get_last_master_hash(self):
        """Returns the hash of the last block.
        """
        return self._master_chain[-1].compute_hash()

    def get_peers(self):
        """ Returns all peers of the newtork.
        """
        return self.broadcast.get_peers()

    def difficulty(self):
        """Returns the difficulty level.
        """
        return self._difficulty

    def add_transaction(self, transaction, broadcast = True):
        """Adds a transaction to your current list of transactions,
        and broadcasts it to your Blockchain network.
        
        NB : If the `mine` method is called, it will collect the current list
        of transactions, and attempt to mine a block with those.
        """
        # print("Added transaction" ,transaction.__dict__)
        self._pending_transactions.append(transaction)
        if broadcast:
            self.broadcast.broadcast("transaction",json.dumps(transaction.__dict__,sort_keys=True))
        return

    def confirm_block(self,foreign_block):
        """Pass a block to be confirmed by the blockchain.

        Parameters:
        ----------
        foreign_block: Block object
        """


        if self._miner :
            self._confirm_block = True

            print("Confirming an incoming block with hash ",
                    foreign_block.compute_hash())

            if self._add_block(foreign_block):
                self._block_added = True
                print("Block confirmed by other node")      

                local_block_tr = self._block_to_mine.get_transactions()

                for tr in foreign_block.get_transactions():
                    # Remove the incoming block's transaction from the pool
                    if tr in self._pending_transactions:
                        print(tr.key, tr.value)
                        self._pending_transactions.remove(tr)

                        
                    #Remove the incoming block's transaction from the locally mined block transaction list
                    if tr in local_block_tr:
                        local_block_tr.remove(tr)
                
                #The transactions that were not added to the chain get put back in the pool
                for tr in local_block_tr:
                    if tr not in self._pending_transactions:
                        self._pending_transactions.append(tr)

                self._confirm_block = False
                return True
            else:
                #Block is not valid, we continue mining
                # print("Resume mining...")
                #Reset block confirmation fields
                self._confirm_block = False
                return False
            print("Block confirmed by other node")      
        else:
            self._pending_transactions = []
            return self._add_block(foreign_block)

    def mine(self):
        """Implements the mining procedure.
        """
        while(True):
            if not self._pending_transactions:
                time.sleep(1) #Wait before checking new transactions
            else:
                input_tr = copy.deepcopy(self._pending_transactions)
                nb_transactions = len(input_tr)
                self._block_to_mine = Block(index=random.randint(1, sys.maxsize),
                                transactions=input_tr,
                                timestamp=time.time(),
                                previous_hash=self._last_hash)

                #Remove the transactions that were inserted into the block
                del self._pending_transactions[:nb_transactions]

                # print("Processed {} transaction(s) in this block, {} pending".format(nb_transactions, len(self._pending_transactions)))

                if self._proof_of_work(): 
                    self._add_block(self._block_to_mine)

    def is_valid(self):
        """Checks if the current state of the blockchain is valid, 
        meaning, are the sequence of hashes, and the proofs of the
        blocks correct?
        """
        chain = self._master_chain
        last_block = chain[-1]
        previous_hash = last_block._previous_hash
        print("Previous hash",previous_hash)
        it = -1
        while previous_hash != "0":
            #Check if proof is valid and if previous hashes match
            if(previous_hash != chain[it-1].compute_hash() or
                not chain[it].proof(self._difficulty)):
                
                return False
            it = it - 1
            previous_hash = chain[it]._previous_hash
        
        return True


def get_address_best_hash(hashes):
    results = {}
    for hash in hashes.values():
        if(hash in results):
            results[hash] += 1
        else:
            results[hash] = 1
    
    best_hash = max(results.items(), key=operator.itemgetter(1))[0]
    for address,hash in hashes.items():
        if(best_hash == hash):
            return address

    return None

